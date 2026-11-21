"""Per-session message counts and preview texts for thread lists, read in a few grouped queries."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message

__all__ = ["_load_session_preview_maps"]


async def _content_by_session(
    db: AsyncSession,
    session_ids: list[str],
    *,
    role: str | None,
    newest_first: bool,
) -> dict[str, str]:
    """The first (or newest) message content per session; with a role, only non-empty messages of that role."""
    order_by = (
        (Message.created_at.desc(), Message.id.desc()) if newest_first else (Message.created_at.asc(), Message.id.asc())
    )
    conditions = [Message.session_id.in_(session_ids)]
    if role is not None:
        conditions += [Message.role == role, Message.content.is_not(None), Message.content != ""]
    subquery = (
        select(
            Message.session_id.label("session_id"),
            Message.content.label("content"),
            func.row_number().over(partition_by=Message.session_id, order_by=order_by).label("position"),
        )
        .where(*conditions)
        .subquery()
    )
    rows = (
        await db.execute(select(subquery.c.session_id, subquery.c.content).where(subquery.c.position == 1))
    ).all()
    return {str(session_id): str(content or "") for session_id, content in rows}


async def _load_session_preview_maps(
    db: AsyncSession,
    session_ids: list[str],
) -> tuple[dict[str, int], dict[str, str], dict[str, str], dict[str, str]]:
    """Message count, first user message, last message and last assistant message per session."""
    if not session_ids:
        return {}, {}, {}, {}

    message_count_rows = (
        await db.execute(
            select(Message.session_id, func.count(Message.id))
            .where(Message.session_id.in_(session_ids))
            .group_by(Message.session_id)
        )
    ).all()
    message_count_by_session_id = {str(session_id): int(count or 0) for session_id, count in message_count_rows}
    return (
        message_count_by_session_id,
        await _content_by_session(db, session_ids, role="user", newest_first=False),
        await _content_by_session(db, session_ids, role=None, newest_first=True),
        await _content_by_session(db, session_ids, role="assistant", newest_first=True),
    )
