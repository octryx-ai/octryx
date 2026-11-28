"""Attention entries of session handovers: one addressed to the person, and pool entries the person can run now."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, SessionHandover, User, WorkflowRun
from ...time_utils import ensure_utc
from ..project.private_workspace import outside_foreign_private
from ..session.handover_pool import STATUS_PENDING, pool_entries
from .requests import action

_PATH = "/api/v1/session-handovers"


def _link(session_id: str) -> dict[str, str]:
    return {"href": f"/chat?session_id={session_id}", "label": "Open the session"}


async def _direct(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    from .run_items import run_context

    rows = (await db.execute(select(SessionHandover).join(Session, Session.id == SessionHandover.session_id).where(
        SessionHandover.to_user_id == user.id, SessionHandover.status == STATUS_PENDING,
        outside_foreign_private(Session.project_id, user.id)).limit(50))).scalars().all()
    entries = []
    for row in rows:
        giver = await db.get(User, row.from_user_id)
        run = await db.get(WorkflowRun, row.run_id) if row.run_id else None
        context = await run_context(db, run) if run is not None else {"session_id": row.session_id}
        entries.append({
            "key": f"handover:{row.id}", "kind": "handover", "id": run.id if run is not None else row.session_id,
            "title": run.title if run is not None else "A session for you",
            "subtitle": f"from {(giver.display_name or giver.username) if giver is not None else 'someone'}",
            "text": row.reason or "", "severity": "action", **context, "link": _link(row.session_id),
            "created_at": ensure_utc(row.created_at).isoformat() if row.created_at else None,
            "actions": [action("accept", "Take over", path=f"{_PATH}/{row.id}/accept", tone="primary"),
                        action("decline", "Decline", path=f"{_PATH}/{row.id}/decline", body={},
                               input_={"kind": "text", "field": "reason", "label": "Why not?", "placeholder": "",
                                       "required": False})],
        })
    return entries


async def handover_entries(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    entries = await _direct(db, user)
    for entry in await pool_entries(db, user, runnable_only=True):
        if entry["from_user_id"] == user.id:
            continue  # the holder's own run already asks them (its pause)
        entries.append({
            "key": f"pool:{entry['id']}", "kind": "pool", "id": entry["run_id"] or entry["session_id"],
            "title": entry["title"], "subtitle": "In the session pool · you can run it now",
            "text": entry["summary"] or "", "severity": "action", "session_id": entry["session_id"],
            "needs": entry["needs"], "link": _link(entry["session_id"]), "created_at": entry["created_at"],
            "actions": [action("accept", "Take over", path=f"{_PATH}/{entry['id']}/accept", tone="primary")],
        })
    return entries


__all__ = ["handover_entries"]
