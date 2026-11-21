from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession


async def get_owned_chat_session(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
) -> AgentSession:
    session = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user_id))
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
