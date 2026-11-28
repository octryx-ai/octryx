"""A repeated chat send never starts a second turn."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message
from ...models import Session as AgentSession


async def find_idempotent_send_session(
    db: AsyncSession,
    *,
    user_id: str,
    idempotency_key: str | None,
    session_id: str = "",
) -> AgentSession | None:
    key = str(idempotency_key or "").strip()
    if not key:
        return None
    query = (
        select(AgentSession)
        .join(Message, Message.session_id == AgentSession.id)
        .where(Message.idempotency_key == key, Message.role == "user", AgentSession.user_id == user_id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if str(session_id or "").strip():
        query = query.where(AgentSession.id == str(session_id).strip())
    return (await db.execute(query)).scalar_one_or_none()


__all__ = ["find_idempotent_send_session"]
