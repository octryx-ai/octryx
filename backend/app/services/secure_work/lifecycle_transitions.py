"""Best-effort work-item lifecycle transitions at platform flow points."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkItem, WorkItemStateEvent, WorkItemWorkflowDefinition
from ...time_utils import utc_now
from .workflow_access import CODE_PROJECT_MISMATCH
from .workflow_mapping import DEFAULT_WORKFLOW_STATES, normalize_workflow_states, transition_work_item

logger = logging.getLogger(__name__)

STATE_DEVELOPMENT = "development"
STATE_REVIEW = "review"
SOURCE_PLATFORM_LIFECYCLE = "platform_lifecycle"
_DEFAULT_STATE_KEYS = frozenset(state["key"] for state in DEFAULT_WORKFLOW_STATES)
_TERMINAL_STATES = frozenset({"done", "completed", "cancelled", "canceled", "rejected", "superseded"})


async def default_workflow_for_item(
    db: AsyncSession, item: WorkItem
) -> WorkItemWorkflowDefinition | None:
    in_scope = WorkItemWorkflowDefinition.project_id.is_(None)
    if item.project_id:
        in_scope = in_scope | (WorkItemWorkflowDefinition.project_id == item.project_id)
    stmt = (
        select(WorkItemWorkflowDefinition)
        .where(WorkItemWorkflowDefinition.is_active.is_(True), in_scope)
        .order_by(
            WorkItemWorkflowDefinition.is_default.desc(),
            WorkItemWorkflowDefinition.updated_at.desc(),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    project_scoped = [row for row in rows if row.project_id and row.project_id == item.project_id]
    global_rows = [row for row in rows if not row.project_id]
    # Never another Workspace's workflow
    candidates = project_scoped or global_rows
    return candidates[0] if candidates else None


def _not_applied(
    item: WorkItem,
    *,
    status: str,
    reason: str | None,
    to_state: str,
    workflow_id: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    log = logger.warning if status == "refused" or reason == "tracker_refused" else logger.info
    log(
        "work_item_auto_transition_%s source_key=%s reason=%s workflow_id=%s state=%s",
        status,
        item.source_key,
        reason,
        workflow_id,
        to_state,
    )
    result: dict[str, Any] = {"status": status, "to_state": to_state}
    if reason is not None:
        result["reason"] = reason
    if detail is not None:
        result["detail"] = detail
    return result


def _is_scope_refusal(exc: HTTPException) -> bool:
    return (
        exc.status_code == 409
        and isinstance(exc.detail, dict)
        and exc.detail.get("code") == CODE_PROJECT_MISMATCH
    )


def _platform_item(item: WorkItem) -> bool:
    from .platform_items import PLATFORM_SOURCE_TYPE  # noqa: PLC0415 - platform_items imports half the service layer

    return str(item.source_type or "") == PLATFORM_SOURCE_TYPE


def _move_platform_item(
    db: AsyncSession, item: WorkItem, *, current_user: User, to_state: str, reason: str
) -> dict[str, Any]:
    # A platform item has no tracker to map, so the default vocabulary is its workflow; a done or rejected item stays.
    previous = str(item.work_state or "").strip() or "intake"
    if previous in _TERMINAL_STATES:
        return _not_applied(item, status="skipped", reason="terminal_state", to_state=to_state)
    item.work_state = to_state
    item.updated_at = utc_now()
    db.add(WorkItemStateEvent(
        work_item_id=item.id, from_state=previous, to_state=to_state, actor_id=current_user.id, reason=reason,
        source=SOURCE_PLATFORM_LIFECYCLE, dry_run=False,
        jira_sync_preview_json={"mode": "local_only", "will_mutate_jira": False}, conflict_json={},
    ))
    logger.info("work_item_auto_transition_applied source_key=%s state=%s platform_default_states",
                item.source_key, to_state)
    return {"status": "applied", "from_state": previous, "to_state": to_state, "mode": "platform_default_states"}


REASON_JIRA_CHANGED = "jira_changed_since_sync"


async def auto_transition_work_item(
    db: AsyncSession,
    *,
    item: WorkItem,
    current_user: User,
    to_state: str,
    reason: str,
) -> dict[str, Any]:
    if str(item.work_state or "").strip() == to_state:
        return _not_applied(item, status="unchanged", reason=None, to_state=to_state)
    workflow = await default_workflow_for_item(db, item)
    if workflow is None:
        if _platform_item(item) and to_state in _DEFAULT_STATE_KEYS:
            return _move_platform_item(db, item, current_user=current_user, to_state=to_state, reason=reason)
        return _not_applied(item, status="skipped", reason="no_workflow_in_scope", to_state=to_state)
    state_keys = {state["key"] for state in normalize_workflow_states(workflow.states_json)}
    if to_state not in state_keys:
        return _not_applied(item, status="skipped", reason="unknown_state", to_state=to_state,
                            workflow_id=workflow.id)
    try:
        result = await transition_work_item(
            db,
            workflow_id=workflow.id,
            work_item_id=item.id,
            current_user=current_user,
            payload={"to_state": to_state, "reason": reason},
            # An internal flow point (its caller already scoped the item), not a UI apply.
            # The workflow's Workspace scope is still checked there.
            bind_preview=False,
            check_access=False,
        )
    # Lifecycle sync must never break a coding run or a delivery: the outcome is returned
    except HTTPException as exc:
        if _is_scope_refusal(exc):
            return _not_applied(item, status="refused", reason=CODE_PROJECT_MISMATCH, to_state=to_state,
                                workflow_id=workflow.id)
        if exc.status_code == 409 and "changed after the Work Item was last synced" in str(exc.detail):
            # Someone (a person, a Jira automation reacting to the pull request) moved the issue since the last sync:
            # their change stands, the flow goes on (otherwise the run never reaches "done").
            return _not_applied(item, status="skipped", reason=REASON_JIRA_CHANGED, to_state=to_state,
                                workflow_id=workflow.id, detail=str(exc.detail))
        return _not_applied(item, status="skipped", reason="tracker_refused", to_state=to_state,
                            workflow_id=workflow.id, detail=str(exc.detail))
    return {"status": "applied", **result}


__all__ = [
    "REASON_JIRA_CHANGED",
    "STATE_DEVELOPMENT",
    "STATE_REVIEW",
    "auto_transition_work_item",
    "default_workflow_for_item",
]
