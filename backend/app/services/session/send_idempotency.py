"""A repeated chat send never starts a second turn.

The chat composer sends one ``idempotency_key`` per draft message and reuses it on a retry or a
double Enter. Before a turn is prepared, the send path looks up a user message with that key in a
session the same user owns; if there is one, the send answers that session instead of creating a
new thread (or a second turn in the same thread). Keys of other users never match.
"""

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
