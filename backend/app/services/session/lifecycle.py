"""Service-owned chat session lifecycle mutations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from .shared import set_session_metadata_value


async def collect_owned_session_tree(db: AsyncSession, *, root_session_id: str, user_id: str) -> list[Session]:
    sessions = (
        (
            await db.execute(
                select(Session).where(Session.user_id == user_id).order_by(Session.started_at.asc(), Session.id.asc())
            )
        )
        .scalars()
        .all()
    )
    children_by_parent: dict[str, list[Session]] = {}
    root_session: Session | None = None
    for session in sessions:
        if session.id == root_session_id:
            root_session = session
        parent_id = str(session.parent_session_id or "").strip()
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(session)
    if root_session is None:
        return []

    collected: list[Session] = []
    stack = [root_session]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current.id in seen:
            continue
        seen.add(current.id)
        collected.append(current)
        for child in reversed(children_by_parent.get(current.id, [])):
            if child.id not in seen:
                stack.append(child)
    return collected


async def set_session_tree_status(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    status: str,
) -> None:
    sessions = await collect_owned_session_tree(db, root_session_id=session_id, user_id=user_id)
    for tree_session in sessions:
        tree_session.status = status


async def archive_session_tree(db: AsyncSession, *, session_id: str, user_id: str) -> None:
    await set_session_tree_status(db, session_id=session_id, user_id=user_id, status="archived")


async def restore_session_tree(db: AsyncSession, *, session_id: str, user_id: str) -> None:
    await set_session_tree_status(db, session_id=session_id, user_id=user_id, status="active")


def set_session_pinned_state(session: Session, pinned: bool) -> None:
    set_session_metadata_value(session, "pinned", bool(pinned))


__all__ = [
    "archive_session_tree",
    "collect_owned_session_tree",
    "restore_session_tree",
    "set_session_pinned_state",
    "set_session_tree_status",
]
