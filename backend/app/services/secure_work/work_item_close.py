"""The explicit Close action of a Work item: at the source when write-back allows it, else locally."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkItem, WorkItemStateEvent, WorkItemWorkflowDefinition
from ...time_utils import utc_now
from .access import get_scoped_work_item
from .jira.jira_item_upsert import CLOSED_STATE, TERMINAL_STATES
from .lifecycle_transitions import default_workflow_for_item
from .serializers import serialize_state_event
from .sync_policy import executes, load_item_intake, mapped_status
from .transition_outcome import record_refused_transition
from .workflow_mapping import normalize_workflow_mappings, normalize_workflow_states, transition_work_item

CLOSE_SOURCE = "close_action"
AUDIT_CLOSED = "secure_work.work_item_closed"
MODE_SOURCE = "source_transition"
MODE_LOCAL = "local_only"
MODE_ALREADY = "already_closed"
DONE_CATEGORY_TARGET = {"target_status_category": "done"}


def write_back_reason(item: WorkItem, workflow: WorkItemWorkflowDefinition | None) -> str | None:
    # Custom REST's done mapping must name the ``source_status``: there is no status category to fall back on.
    own = _own_write_back(item)
    if str(item.source_type or "") != "jira" and not own:
        return "not_a_jira_item"
    if workflow is None:
        return "no_workflow"
    if not executes(workflow.sync_policy_json, item):  # the intake's own sync_mode, else the workflow's
        return "write_back_disabled"
    states = normalize_workflow_states(workflow.states_json)
    mapping = normalize_workflow_mappings(workflow.mappings_json, states=states).get(CLOSED_STATE) or {}
    if own and not mapped_status(mapping):
        return "done_mapping_not_synced"
    return None if mapping.get("sync_back") else "done_mapping_not_synced"


def _own_write_back(item: WorkItem) -> bool:
    from .intake.registry import source_for

    return str(item.source_type or "") != "jira" and \
        getattr(source_for(item.source_type), "state_sync_driver", None) is not None


def _closed_at_source(item: WorkItem) -> bool:
    fields = item.source_fields_json if isinstance(item.source_fields_json, dict) else {}
    mapping = fields.get("status_mapping") if isinstance(fields.get("status_mapping"), dict) else {}
    return mapping.get("category") == "done"


def _refusal_code(exc: HTTPException) -> str:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    coded = detail.get("code") or detail.get("reason")
    if coded:
        return str(coded)
    return {409: "transition_not_available", 422: "write_back_not_configured"}.get(exc.status_code,
                                                                                    "write_back_failed")


def _result(item: WorkItem, *, mode: str, reason: str | None, event: WorkItemStateEvent | dict | None,
            jira: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "closed": True,
        "mode": mode,
        "item_id": item.id,
        "source_key": item.source_key,
        "work_state": item.work_state,
        "source_status": item.source_status,
        "write_back": {"enabled": reason is None, "reason": reason},
        "jira": jira,
        "event": serialize_state_event(event) if isinstance(event, WorkItemStateEvent) else event,
    }


def _audit(user: User, item: WorkItem, *, mode: str, from_state: str | None, reason: str | None,
           write_back: str | None) -> AuditLog:
    return AuditLog(user_id=user.id, action=AUDIT_CLOSED, resource_type="work_item", resource_id=item.id,
                    project_id=item.project_id,
                    details={"source_key": item.source_key, "mode": mode, "from_state": from_state,
                             "reason": reason, "write_back_reason": write_back})


async def _close_locally(db: AsyncSession, item: WorkItem, workflow: WorkItemWorkflowDefinition | None,
                         user: User, *, reason: str | None, why_local: str) -> dict[str, Any]:
    from_state = item.work_state
    event = WorkItemStateEvent(
        work_item_id=item.id, workflow_id=workflow.id if workflow else None, from_state=from_state,
        to_state=CLOSED_STATE, actor_id=user.id, reason=reason, source=CLOSE_SOURCE, dry_run=False,
        jira_sync_preview_json={"mode": MODE_LOCAL, "will_mutate_jira": False, "local_only_reason": why_local},
        conflict_json={},
    )
    item.work_state, item.updated_at = CLOSED_STATE, utc_now()
    db.add(event)
    db.add(_audit(user, item, mode=MODE_LOCAL, from_state=from_state, reason=reason, write_back=why_local))
    await db.flush()
    return _result(item, mode=MODE_LOCAL, reason=why_local, event=event)


async def _close_at_source(db: AsyncSession, item: WorkItem, workflow: WorkItemWorkflowDefinition, user: User,
                           *, reason: str | None) -> dict[str, Any]:
    from_state = item.work_state
    try:
        applied = await transition_work_item(
            db, workflow_id=workflow.id, work_item_id=item.id, current_user=user,
            payload={"to_state": CLOSED_STATE, "reason": reason or "", "source": CLOSE_SOURCE},
            bind_preview=False, jira_target=DONE_CATEGORY_TARGET, by_person=True,
        )
    except (HTTPException, httpx.HTTPError) as exc:
        refusal = exc if isinstance(exc, HTTPException) else HTTPException(status_code=502, detail=str(exc))
        if refusal.status_code in (401, 403, 404):
            raise
        code = _refusal_code(refusal)
        detail = {"closed": False, "mode": MODE_SOURCE, "code": code, "source_key": item.source_key,
                  "message": str(refusal.detail.get("message") if isinstance(refusal.detail, dict)
                                 else refusal.detail)}
        coded = HTTPException(status_code=refusal.status_code, detail=detail)
        await record_refused_transition(db, item=item, workflow=workflow, current_user=user, to_state=CLOSED_STATE,
                                        reason=reason, refusal=coded)
        raise coded from exc
    execution = dict(applied["preview"]["jira_sync_preview"].get("execution") or {})
    jira = {key: execution.get(key) for key in ("transition_id", "transition_name", "resulting_status",
                                                "comment_posted")}
    db.add(_audit(user, item, mode=MODE_SOURCE, from_state=from_state, reason=reason, write_back=None))
    await db.flush()
    return _result(item, mode=MODE_SOURCE, reason=None, event=applied["event"], jira=jira)


async def close_preview(db: AsyncSession, item: WorkItem) -> dict[str, Any]:
    await load_item_intake(db, item)
    why_local = write_back_reason(item, await default_workflow_for_item(db, item))
    return {"close_mode": MODE_LOCAL if why_local is not None else MODE_SOURCE, "write_back_reason": why_local}


async def close_work_item(
    db: AsyncSession, *, work_item_id: str, current_user: User, payload: dict[str, Any]
) -> dict[str, Any]:
    item = await get_scoped_work_item(db, current_user, work_item_id)
    reason = str(payload.get("reason") or "").strip()[:2000] or None
    workflow = await default_workflow_for_item(db, item)
    await load_item_intake(db, item)
    why_local = write_back_reason(item, workflow)
    terminal = str(item.work_state or "") in TERMINAL_STATES
    if terminal and (why_local is not None or _closed_at_source(item)):
        return _result(item, mode=MODE_ALREADY, reason=why_local, event=None)
    if why_local is not None:
        return await _close_locally(db, item, workflow, current_user, reason=reason, why_local=why_local)
    return await _close_at_source(db, item, workflow, current_user, reason=reason)


__all__ = ["AUDIT_CLOSED", "CLOSE_SOURCE", "MODE_ALREADY", "MODE_LOCAL", "MODE_SOURCE", "close_preview",
           "close_work_item", "write_back_reason"]
