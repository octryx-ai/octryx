"""Prepare a chat turn in the test's database session, with the ``/chat/api`` HTTP errors.

The service owner (``services/session/turn_prepare.prepare_turn_in_session``) without the
preparation lock and the proposal prefetch, rendered like the chat adapter renders it.
"""

from __future__ import annotations

from dataclasses import replace

from app.models import Session as AgentSession
from app.services.session.turn_prepare import prepare_turn_in_session
from app.services.session.turn_refusals import TurnRefusedError
from app.web._helpers.chat_turn_prepare import chat_refusal_http_exception, chat_turn_request


async def prepare_chat_turn(*, db, user, precomputed_proposal=None, agent_type_explicit=False, **request_kwargs):
    """``(session, runtime_target_id, thinking_level, agent_payload)``; an automatic runtime is ``""``.

    ``agent_type_explicit`` is the service owner's flag for programmatic callers (secure-work coding
    execution); the chat adapter never sets it, so it is applied to the owner's request here.
    """
    request = replace(chat_turn_request(user_id=user.id, **request_kwargs), agent_type_explicit=agent_type_explicit)
    try:
        prepared = await prepare_turn_in_session(
            db,
            user=user,
            request=request,
            precomputed_proposal=precomputed_proposal,
        )
    except TurnRefusedError as refused:
        raise chat_refusal_http_exception(refused.refusal) from None
    session = await db.get(AgentSession, prepared.session_id)
    return session, prepared.runtime_target_id or "", prepared.thinking_level, prepared.agent_definition
