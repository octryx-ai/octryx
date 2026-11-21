"""The work-role audit log: who changed which function, role, assignment, switch or SSO mapping, before and after.

Role edits are no Rules publish, so this log is their only record; every admin write goes
through :func:`record` in the same transaction as the change.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.work_role_model import WorkRoleAuditEvent

DEFAULT_PAGE = 100


def record(db: AsyncSession, *, actor_id: str, action: str, target_type: str, target_id: str, label: str = "",
           workspace_id: str | None = None, before: dict | None = None, after: dict | None = None,
           reason: str | None = None) -> WorkRoleAuditEvent:
    event = WorkRoleAuditEvent(actor_user_id=actor_id, action=action, project_id=workspace_id,
                               target_type=target_type, target_id=target_id, target_label=label[:200],
                               before_json=before, after_json=after, reason=reason)
    db.add(event)
    return event


async def list_events(db: AsyncSession, *, workspace_id: str | None = None, target_id: str | None = None,
                      before: datetime | None = None, limit: int = DEFAULT_PAGE) -> tuple[list[dict[str, Any]],
                                                                                         str | None]:
    """Newest first; ``next_before`` pages on (no cap on the history, only on one page)."""
    query = select(WorkRoleAuditEvent, User).outerjoin(User, User.id == WorkRoleAuditEvent.actor_user_id)
    if workspace_id:
        query = query.where(WorkRoleAuditEvent.project_id == workspace_id)
    if target_id:
        query = query.where(WorkRoleAuditEvent.target_id == target_id)
    if before is not None:
        query = query.where(WorkRoleAuditEvent.created_at < before)
    rows = (await db.execute(query.order_by(WorkRoleAuditEvent.created_at.desc(), WorkRoleAuditEvent.id.desc())
                             .limit(limit + 1))).all()
    events = [{"id": event.id, "at": event.created_at.isoformat(),
               "actor": {"user_id": event.actor_user_id,
                         "label": (user.display_name or user.username) if user else None},
               "action": event.action, "workspace_id": event.project_id, "target_type": event.target_type,
               "target_id": event.target_id, "target_label": event.target_label, "before": event.before_json,
               "after": event.after_json, "reason": event.reason} for event, user in rows[:limit]]
    next_before = rows[limit - 1][0].created_at.isoformat() if len(rows) > limit else None
    return events, next_before


__all__ = ["list_events", "record"]
