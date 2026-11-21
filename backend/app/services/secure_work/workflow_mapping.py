from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkItem, WorkItemStateEvent, WorkItemWorkflowDefinition
from ...time_utils import utc_now
from ..access_control import require_existing_workspace
from .jira.jira_state_sync import will_write_jira
from .jira_values import blank_to_none, object_value, parse_datetime, string_list
from .serializers import serialize_state_event, serialize_transition_preview, serialize_workflow_definition
from .sync_policy import (
    SYNC_MODE_DRY_RUN,
    load_item_intake,
    mapped_status,
    mapped_transition,
    sync_mode,
)
from .tracker_drivers import execute_tracker_state_sync
from .transition_outcome import record_refused_transition, record_write_back
from .transition_preview import finish_preview, require_active, require_previewed
from .workflow_access import (
    WORKFLOW_NOT_FOUND,
    require_project_access,
    require_transition_access,
    require_workflow_access,
    require_workflow_scope,
    visible_project_ids,
)
from .workflow_lifecycle import transition_refusal, validate_mapping_keys

DEFAULT_WORKFLOW_STATES: tuple[dict[str, str], ...] = (
    {"key": "intake", "label": "Intake", "description": "Imported work awaiting triage."},
    {"key": "clarification", "label": "Clarification", "description": "Needs product, team, or Jira clarification."},
    {"key": "ready_for_plan", "label": "Ready for plan", "description": "Scope is clear enough to plan."},
    {"key": "planning", "label": "Planning", "description": "Implementation plan is being prepared."},
    {"key": "plan_review", "label": "Plan review", "description": "Human review of plan and risk."},
    {"key": "ready_for_development", "label": "Ready for development", "description": "Approved for implementation."},
    {"key": "development", "label": "Development", "description": "Code or configuration change is in progress."},
    {"key": "validation", "label": "Validation", "description": "Automated and manual validation is running."},
    {"key": "review", "label": "Review", "description": "Pull request or change review is active."},
    {"key": "changes_requested", "label": "Changes requested", "description": "Reviewer requested changes."},
    {"key": "ready_to_merge", "label": "Ready to merge", "description": "Approved and ready for merge."},
    {"key": "done", "label": "Done", "description": "Work is complete."},
    {"key": "blocked", "label": "Blocked", "description": "Progress is blocked and needs attention."},
    {"key": "rejected", "label": "Rejected", "description": "Work will not be executed."},
)

DEFAULT_SYNC_POLICY = {
    "sync_mode": SYNC_MODE_DRY_RUN,
    "conflict_policy": "require_review",
}


async def create_workflow_definition(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    project_id = blank_to_none(payload.get("project_id"))
    await require_existing_workspace(db, project_id)
    await require_project_access(db, current_user, project_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    states = normalize_workflow_states(payload.get("states"))
    validate_mapping_keys(payload.get("mappings"), states)  # never a silently dropped mapping
    mappings = normalize_workflow_mappings(payload.get("mappings"), states=states)
    row = WorkItemWorkflowDefinition(
        name=name[:220],
        description=str(payload.get("description") or "").strip() or None,
        project_id=project_id,
        states_json=states,
        mappings_json=mappings,
        sync_policy_json=_normalize_sync_policy(payload.get("sync_policy")),
        is_default=bool(payload.get("is_default", False)),
        is_active=bool(payload.get("is_active", True)),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(row)
    await db.flush()
    return serialize_workflow_definition(row)


async def get_workflow_definition(db: AsyncSession, workflow_id: str) -> WorkItemWorkflowDefinition:
    row = await db.get(WorkItemWorkflowDefinition, workflow_id)
    if row is None:
        raise HTTPException(status_code=404, detail=WORKFLOW_NOT_FOUND)
    return row


async def list_workflow_definitions(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    include_inactive: bool = False,
    current_user: User | None = None,
) -> list[dict[str, Any]]:
    stmt = select(WorkItemWorkflowDefinition)
    if current_user is not None:
        # Global workflows and the caller's Workspaces only.
        scope = await visible_project_ids(db, current_user, project_id)
        if scope is not None:
            stmt = stmt.where(
                WorkItemWorkflowDefinition.project_id.in_(scope) | WorkItemWorkflowDefinition.project_id.is_(None)
            )
    if project_id:
        stmt = stmt.where(WorkItemWorkflowDefinition.project_id == project_id)
    if not include_inactive:
        stmt = stmt.where(WorkItemWorkflowDefinition.is_active.is_(True))
    stmt = stmt.order_by(
        WorkItemWorkflowDefinition.is_default.desc(),
        WorkItemWorkflowDefinition.updated_at.desc(),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_workflow_definition(row) for row in rows]


async def dry_run_work_item_transition(
    db: AsyncSession,
    *,
    workflow_id: str,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    workflow = await get_workflow_definition(db, workflow_id)
    await require_workflow_access(db, current_user, workflow, change=False)  # another Workspace's: a missing one
    item = await _get_work_item(db, work_item_id)
    await require_transition_access(db, current_user, workflow, item)  # ACL (403), then scope (409)
    require_active(workflow)
    preview = build_transition_preview(work_item=item, workflow=workflow, payload=payload)
    if preview["valid"]:
        await finish_preview(db, item=item, workflow=workflow, preview=preview)  # effects_hash
    event = _create_state_event(
        item=item,
        workflow=workflow,
        current_user=current_user,
        payload=payload,
        preview=preview,
        dry_run=True,
    )
    db.add(event)
    db.add(_audit_log(current_user, item, workflow, preview, action="secure_work.transition_dry_run"))
    await db.flush()
    return {"preview": serialize_transition_preview(preview), "event": serialize_state_event(event)}


async def transition_work_item(
    db: AsyncSession,
    *,
    workflow_id: str,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
    bind_preview: bool = True,
    check_access: bool = True,
    jira_target: dict[str, Any] | None = None,
    by_person: bool | None = None,
) -> dict[str, Any]:
    """Apply a transition. ``bind_preview`` (the UI path) requires the confirmed ``effects_hash``;
    ``check_access`` False only for internal flow points whose caller already scoped the item; the
    workflow's Workspace scope is checked either way, before anything is read from or written to a tracker.
    ``jira_target`` (the Close action's done status category) fills a synced mapping that names no Jira target.
    ``by_person`` (default: ``bind_preview``, the UI apply a person confirmed) tells a source's write-back whether a
    person decided this transition; an unattended one (a run, a sync) only proposes where the source requires it
    (``custom_rest/write_back``)."""
    workflow = await get_workflow_definition(db, workflow_id)
    if check_access:
        await require_workflow_access(db, current_user, workflow, change=False)  # another Workspace's: a missing one
    item = await _get_work_item(db, work_item_id)
    if check_access:
        await require_transition_access(db, current_user, workflow, item)  # ACL (403), then scope (409)
    else:
        require_workflow_scope(workflow, item)  # an internal flow point skips the ACL, never the scope
    try:
        require_active(workflow)
        preview = build_transition_preview(work_item=item, workflow=workflow, payload=payload)
        if not preview["valid"]:
            raise HTTPException(
                status_code=422, detail=transition_refusal(preview, normalize_workflow_states(workflow.states_json))
            )
        sync = preview["jira_sync_preview"]
        if jira_target and sync["sync_back"] and not (sync["transition"] or sync["target_status"]):
            sync.update(jira_target)
            sync["will_mutate_jira"] = _will_write(item, workflow, sync)
        await finish_preview(db, item=item, workflow=workflow, preview=preview)
        if bind_preview:
            require_previewed(preview, payload.get("effects_hash"))
        if preview["conflict"].get("has_conflict") and not bool(payload.get("allow_conflict")):
            raise HTTPException(status_code=409, detail="Jira changed after the Work Item was last synced")
        # Tracker first, local state second: a failed write-back must not leave
        # the platform ahead of the ticket. The source-type driver raises with
        # the issue's real transition offers when the mapped transition is
        # unreachable; platform items are local-only by contract.
        person = bind_preview if by_person is None else by_person
        preview["applied_by"] = {"person": bool(person), "user_id": current_user.id}
        tracker_sync_result = await execute_tracker_state_sync(db, item=item, workflow=workflow, preview=preview)
        preview.pop("applied_by", None)
    except HTTPException as refusal:
        if refusal.status_code == 409 and bind_preview:  # a refused UI apply is on the timeline
            await record_refused_transition(db, item=item, workflow=workflow, current_user=current_user,
                                            to_state=_state_key(payload.get("to_state")),
                                            reason=str(payload.get("reason") or "").strip(), refusal=refusal)
        raise
    record_write_back(item, tracker_sync_result)  # Jira's resulting status and labels, right away
    if tracker_sync_result is not None:
        preview["jira_sync_preview"] = {
            **preview["jira_sync_preview"],
            "mode": _executed_mode(tracker_sync_result),
            "will_mutate_jira": _executed_mode(tracker_sync_result) == "executed",
            "execution": tracker_sync_result,
        }
    event = _create_state_event(
        item=item,
        workflow=workflow,
        current_user=current_user,
        payload=payload,
        preview=preview,
        dry_run=False,
    )
    item.work_state = preview["to_state"]
    item.updated_at = utc_now()
    db.add(event)
    db.add(_audit_log(current_user, item, workflow, preview, action="secure_work.transition_applied"))
    await db.flush()
    return {
        "item_id": item.id,
        "work_state": item.work_state,
        "preview": serialize_transition_preview(preview),
        "event": serialize_state_event(event),
    }


async def list_work_item_state_events(db: AsyncSession, work_item_id: str) -> list[dict[str, Any]]:
    stmt = (
        select(WorkItemStateEvent)
        .where(WorkItemStateEvent.work_item_id == work_item_id)
        .order_by(WorkItemStateEvent.created_at.desc())
        .limit(100)
    )
    return [serialize_state_event(row) for row in (await db.execute(stmt)).scalars().all()]


def build_transition_preview(
    *,
    work_item: WorkItem,
    workflow: WorkItemWorkflowDefinition,
    payload: dict[str, Any],
) -> dict[str, Any]:
    to_state = _state_key(payload.get("to_state"))
    states = normalize_workflow_states(workflow.states_json)
    state_keys = {state["key"] for state in states}
    if not to_state:
        return _invalid_preview(work_item, workflow, to_state="", error="to_state is required")
    if to_state not in state_keys:
        return _invalid_preview(work_item, workflow, to_state=to_state, error=f"Unknown workflow state: {to_state}")
    mappings = normalize_workflow_mappings(workflow.mappings_json, states=states)
    mapping = mappings.get(to_state, {})
    conflict = _build_conflict(work_item, payload.get("source_jira_updated_at"))
    jira_preview = {
        "mode": "dry_run",
        "will_mutate_jira": False,
        "target_status": blank_to_none(mapped_status(mapping)),
        "transition": blank_to_none(mapped_transition(mapping)),
        "comment_template": str(mapping.get("comment_template") or "").strip(),
        "labels": string_list(mapping.get("labels")),
        "custom_fields": object_value(mapping.get("custom_fields")),
        "sync_back": bool(mapping.get("sync_back", False)),
        "local_only": not bool(mapping.get("sync_back", False)),
    }
    preview = {
        "valid": True,
        "error": None,
        "workflow_id": workflow.id,
        "work_item_id": work_item.id,
        "source_key": work_item.source_key,
        "from_state": work_item.work_state,
        "to_state": to_state,
        "reason": str(payload.get("reason") or "").strip(),
        "jira_sync_preview": jira_preview,
        "conflict": conflict,
    }
    # The preview tells the truth about the apply (its effects follow in ``finish_preview``).
    jira_preview["will_mutate_jira"] = _will_write(work_item, workflow, jira_preview)
    jira_preview["effects"] = []
    return preview


def _will_write(item: WorkItem, workflow: WorkItemWorkflowDefinition, sync_preview: dict[str, Any]) -> bool:
    """Whether the apply writes to the item's source: Jira's rule, or the registered source's own ``will_write``."""
    from .intake.registry import source_for

    own = getattr(source_for(item.source_type), "will_write", None)
    return bool(own(item, workflow, sync_preview)) if own is not None else will_write_jira(item, workflow, sync_preview)


def _executed_mode(result: dict[str, Any]) -> str:
    """``executed``, ``no_driver``, or ``proposed`` (an unattended write-back a person still has to apply)."""
    status = str(result.get("status") or "")
    return status if status in ("no_driver", "proposed") else "executed"


def normalize_workflow_states(value: Any) -> list[dict[str, str]]:
    raw_states = value if isinstance(value, list) and value else list(DEFAULT_WORKFLOW_STATES)
    states: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw_states:
        if isinstance(entry, str):
            key = _state_key(entry)
            label = entry.replace("_", " ").strip().title()
            description = ""
        elif isinstance(entry, dict):
            key = _state_key(entry.get("key") or entry.get("name"))
            label = str(entry.get("label") or key.replace("_", " ").title()).strip()
            description = str(entry.get("description") or "").strip()
        else:
            continue
        if not key or key in seen:
            continue
        seen.add(key)
        states.append({"key": key, "label": label[:120], "description": description[:500]})
    return states or list(DEFAULT_WORKFLOW_STATES)


def normalize_workflow_mappings(value: Any, *, states: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    # Keys are normalized like the validation does ("Development" is "development"), never dropped.
    raw = {_state_key(key): entry for key, entry in object_value(value).items()}
    normalized: dict[str, dict[str, Any]] = {}
    for state in states:
        key = state["key"]
        entry = object_value(raw.get(key))
        # The source-neutral names (``sync_policy``).
        normalized[key] = {
            "source_status": blank_to_none(mapped_status(entry)),
            "source_transition": blank_to_none(mapped_transition(entry)),
            "comment_template": str(entry.get("comment_template") or "").strip(),
            "labels": string_list(entry.get("labels")),
            "custom_fields": object_value(entry.get("custom_fields")),
            "sync_back": bool(entry.get("sync_back", False)),
        }
    return normalized


async def _get_work_item(db: AsyncSession, work_item_id: str) -> WorkItem:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    await load_item_intake(db, item)  # its intake's own sync_mode decides write-back (``sync_policy``)
    return item


def _create_state_event(
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition,
    current_user: User,
    payload: dict[str, Any],
    preview: dict[str, Any],
    dry_run: bool,
) -> WorkItemStateEvent:
    return WorkItemStateEvent(
        work_item_id=item.id,
        workflow_id=workflow.id,
        from_state=item.work_state,
        to_state=preview["to_state"],
        actor_id=current_user.id,
        reason=str(payload.get("reason") or "").strip() or None,
        source=str(payload.get("source") or "manual").strip()[:80] or "manual",
        dry_run=dry_run,
        jira_sync_preview_json=preview["jira_sync_preview"],
        conflict_json=preview["conflict"],
    )


def _audit_log(
    current_user: User,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition,
    preview: dict[str, Any],
    *,
    action: str,
) -> AuditLog:
    return AuditLog(
        user_id=current_user.id,
        action=action,
        resource_type="work_item",
        resource_id=item.id,
        details={
            "source_key": item.source_key,
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "from_state": preview["from_state"],
            "to_state": preview["to_state"],
            "reason": preview["reason"],
            "conflict": preview["conflict"],
            "jira_sync_preview": preview["jira_sync_preview"],
        },
    )


def _normalize_sync_policy(value: Any) -> dict[str, Any]:
    given = object_value(value)
    policy = {**DEFAULT_SYNC_POLICY, **given}
    # Write-back is a double opt-in: only the explicit "execute" mode writes to the source, and even then only for
    # states whose mapping sets sync_back.
    policy["sync_mode"] = sync_mode(given) or SYNC_MODE_DRY_RUN
    return policy


def _build_conflict(work_item: WorkItem, source_jira_updated_at: Any) -> dict[str, Any]:
    external_updated_at = parse_datetime(source_jira_updated_at)
    if external_updated_at is None:
        return {"has_conflict": False, "reason": None}
    last_seen = work_item.last_source_updated_at
    has_conflict = last_seen is not None and external_updated_at > last_seen
    return {
        "has_conflict": has_conflict,
        "reason": "source_changed_after_last_sync" if has_conflict else None,
        "last_source_updated_at": last_seen.isoformat() if last_seen else None,
        "source_jira_updated_at": external_updated_at.isoformat(),
    }


def _invalid_preview(
    work_item: WorkItem,
    workflow: WorkItemWorkflowDefinition,
    *,
    to_state: str,
    error: str,
) -> dict[str, Any]:
    return {
        "valid": False,
        "error": error,
        "workflow_id": workflow.id,
        "work_item_id": work_item.id,
        "source_key": work_item.source_key,
        "from_state": work_item.work_state,
        "to_state": to_state,
        "reason": "",
        "jira_sync_preview": {
            "mode": "dry_run",
            "will_mutate_jira": False,
            "target_status": None,
            "transition": None,
            "comment_template": "",
            "labels": [],
            "custom_fields": {},
            "sync_back": False,
            "local_only": True,
            "effects": [],
        },
        "conflict": {"has_conflict": False, "reason": None},
    }


def _state_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")[:80]
