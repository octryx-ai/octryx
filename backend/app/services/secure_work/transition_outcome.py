"""What a transition apply leaves behind, applied or refused.

- **Applied with a Jira write-back:** the item takes Jira's resulting status and the labels that were
  really added right away, so the board and the detail show the truth before the next sync.
- **Refused:** a refused UI apply (409: stale preview, deactivated workflow, Jira changed since the sync,
  issue outside the allowlist, or a transition Jira does not offer) is recorded as a state event with
  ``source: "transition_refused"`` and an audit row ``secure_work.transition_refused``. They are written in
  their own commit, because the request rolls back. Nothing else is written: the item keeps its state.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkItem, WorkItemStateEvent, WorkItemWorkflowDefinition
from .jira_values import string_list

SOURCE_REFUSED = "transition_refused"
AUDIT_REFUSED = "secure_work.transition_refused"
MAX_DETAIL_CHARS = 1000


def record_write_back(item: WorkItem, result: dict[str, Any] | None) -> None:
    """Keep Jira's resulting status and the applied labels on the item."""
    if not isinstance(result, dict) or not result.get("executed"):
        return
    status = result.get("resulting_status")
    if isinstance(status, str) and status.strip():
        item.source_status = status.strip()[:120]
    applied = string_list(result.get("labels_applied"))
    if applied:
        current = list(item.labels_json or [])
        item.labels_json = current + [label for label in applied if label not in current]


def _detail(refusal: HTTPException) -> dict[str, Any]:
    detail = refusal.detail
    if isinstance(detail, dict):
        code = detail.get("code") or detail.get("reason")
        return {"code": str(code or "refused"), "message": str(detail.get("message") or "")[:MAX_DETAIL_CHARS]}
    return {"code": "refused", "message": str(detail or "")[:MAX_DETAIL_CHARS]}


async def record_refused_transition(
    db: AsyncSession,
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition,
    current_user: User,
    to_state: str,
    reason: str | None,
    refusal: HTTPException,
) -> None:
    """Record a refused apply as a timeline event and an audit row, in its own commit."""
    detail = _detail(refusal)
    db.add(WorkItemStateEvent(
        work_item_id=item.id,
        workflow_id=workflow.id,
        from_state=item.work_state,
        to_state=to_state,
        actor_id=current_user.id,
        reason=reason or None,
        source=SOURCE_REFUSED,
        dry_run=False,
        jira_sync_preview_json={"mode": "refused", "will_mutate_jira": False, "refusal": detail},
        conflict_json={},
    ))
    db.add(AuditLog(
        user_id=current_user.id,
        action=AUDIT_REFUSED,
        resource_type="work_item",
        resource_id=item.id,
        details={"source_key": item.source_key, "workflow_id": workflow.id, "from_state": item.work_state,
                 "to_state": to_state, "refusal_code": detail["code"]},
    ))
    await db.commit()


__all__ = ["AUDIT_REFUSED", "SOURCE_REFUSED", "record_refused_transition", "record_write_back"]
