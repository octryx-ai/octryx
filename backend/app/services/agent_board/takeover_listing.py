"""The UI shape of takeovers: who asked whom for which item, its state and the latest handoff."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem, WorkItemTakeover
from ...time_utils import utc_now
from .claim_values import iso
from .envelope import user_refs
from .handoffs import latest_handoff
from .takeover_status import DECIDED_BY_HUMAN, DECIDED_BY_SYSTEM, effective_status


async def takeover_views(db: AsyncSession, rows: list[WorkItemTakeover]) -> list[dict[str, Any]]:
    if not rows:
        return []
    items = {
        item.id: item
        for item in (
            await db.execute(select(WorkItem).where(WorkItem.id.in_(sorted({row.work_item_id for row in rows}))))
        ).scalars().all()
    }
    users = await user_refs(db, [value for row in rows for value in (row.from_user_id, row.to_user_id,
                                                                       row.decided_by)])
    now, views = utc_now(), []
    for row in rows:
        item = items.get(row.work_item_id)
        handoff = await latest_handoff(db, row.work_item_id)
        views.append(
            {
                "id": row.id,
                "project_id": row.project_id,
                "work_item": {"id": item.id, "key": item.source_key, "title": item.title} if item else None,
                "from": {"user": users.get(row.from_user_id) if row.from_user_id else None,
                         "agent_hash": row.from_agent_hash},
                "to": {"user": users.get(row.to_user_id), "agent_hash": row.to_agent_hash},
                "status": effective_status(row, now),
                "reason": row.reason,
                "automatic": bool(row.automatic),
                "message_id": row.message_id,
                "expires_at": iso(row.expires_at),
                "created_at": iso(row.created_at),
                "decided_at": iso(row.decided_at),
                "decided_by": _decided_by(row, users),
                "policy_mode": row.policy_mode or "confirm",
                "handoff": {"id": handoff.id, "version": handoff.version} if handoff else None,
            }
        )
    return views


def _decided_by(row: WorkItemTakeover, users: dict[str, dict[str, str]]) -> dict[str, Any] | None:
    if row.decided_at is None:
        return None
    if row.decided_by_kind == DECIDED_BY_SYSTEM:
        return {"kind": DECIDED_BY_SYSTEM}
    return {"kind": DECIDED_BY_HUMAN, "user": users.get(row.decided_by) if row.decided_by else None}
