"""Prepare a chat turn in the test's database session, with the ``/chat/api`` HTTP errors."""

from __future__ import annotations

from dataclasses import replace

from app.models import Session as AgentSession
from app.services.session.turn_prepare import prepare_turn_in_session
from app.services.session.turn_refusals import TurnRefusedError
from app.web._helpers.chat_turn_prepare import chat_refusal_http_exception, chat_turn_request


async def prepare_chat_turn(*, db, user, agent_type_explicit=False, **request_kwargs):
    request = replace(chat_turn_request(user_id=user.id, **request_kwargs), agent_type_explicit=agent_type_explicit)
    try:
        prepared = await prepare_turn_in_session(db, user=user, request=request)
    except TurnRefusedError as refused:
        raise chat_refusal_http_exception(refused.refusal) from None
    session = await db.get(AgentSession, prepared.session_id)
    return session, prepared.runtime_target_id or "", prepared.thinking_level, prepared.agent_definition
