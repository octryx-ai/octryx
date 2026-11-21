"""``/chat/api/send``: a repeated send (same ``idempotency_key``) answers its thread and starts nothing."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.runtime_defaults import DEFAULT_AGENT_MODE_KEY
from ...models import User
from ...services.session.send_idempotency import find_idempotent_send_session
from .chat_turn_ack_state import _build_chat_turn_ack_state


async def repeated_send_response(request: Request, db: AsyncSession, *, user: User, payload) -> JSONResponse | None:
    session = await find_idempotent_send_session(
        db, user_id=user.id, idempotency_key=payload.idempotency_key, session_id=payload.session_id or ""
    )
    if session is None:
        return None
    state = await _build_chat_turn_ack_state(
        request,
        db,
        user=user,
        session=session,
        runtime_target_id=payload.runtime_target_id,
        thinking_level=payload.thinking_level or "light",
        agent_id=payload.agent_id,
        agent_type=session.agent_type or DEFAULT_AGENT_MODE_KEY,
    )
    return JSONResponse(state)
