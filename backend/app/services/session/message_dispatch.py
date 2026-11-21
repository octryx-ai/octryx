"""``/api/v1/sessions/{id}/messages``: prepare the turn like ``/chat/api``, run it inside the request.

Preparation is the one owner of both paths (``turn_start.prepare_turn``, scope
``existing``): the same refusal states, the session marked ``running`` / ``in_progress``
with its process ownership, the double-text guard, the runtime target / thinking level / agent
resolution and the execution profile. The turn then runs as a registered task
(``turn_runner.run_request_turn``), so ``turn_stop`` stops it like a chat turn, and is
finished by the same completion step (``turn_settlement``) or failure settlement
(``turn_failure``). The response is the turn's messages, from its user message on.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import core as db_core
from ...models import Message
from ...schemas.operations.session import MessageResponse
from ...time_utils import utc_isoformat
from .turn_refusals import TurnRefusal
from .turn_request import SESSION_SCOPE_EXISTING, TurnRequest
from .turn_runner import run_request_turn
from .turn_start import prepare_turn


def build_dispatched_message_response(message: Message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        tool_calls=message.tool_calls,
        tool_results=message.tool_results,
        model=message.model,
        tokens_in=message.tokens_in,
        tokens_out=message.tokens_out,
        cost=float(message.cost) if message.cost else 0,
        created_at=utc_isoformat(message.created_at) or "",
    )


async def _turn_messages(db: AsyncSession, *, session_id: str, user_message_id: str) -> list[MessageResponse]:
    user_message = await db.get(Message, user_message_id)
    query = select(Message).where(Message.session_id == session_id)
    if user_message is not None and user_message.created_at is not None:
        query = query.where(Message.created_at >= user_message.created_at)
    result = await db.execute(query.order_by(Message.created_at.asc()))
    return [build_dispatched_message_response(item) for item in result.scalars().all()]


async def send_session_message(
    db: AsyncSession,
    *,
    session_id: str,
    content: str,
    user_id: str,
    run_agent_func: Callable[..., Any] | None = None,
    project_id: str | None = None,
    agent_type: str = "",
    workflow_key: str = "",
    workflow_decisions: dict[str, str] | None = None,
    runtime_target_id: str | None = None,
    thinking_level: str | None = None,
    agent_id: str | None = None,
    session_factory=None,
) -> list[MessageResponse] | TurnRefusal:
    """Run one turn on the existing session; the refusal when it may not start.

    ``None`` for ``runtime_target_id`` / ``thinking_level`` / ``agent_id`` means "not
    chosen": the session's, the agent's or the Workspace's default applies, as on
    ``/chat/api``. A value is an explicit choice. ``run_agent_func`` defaults to the
    runner's ``run_agent`` (the one seam of both paths).
    """
    session_factory = session_factory or db_core.async_session_factory
    prepared = await prepare_turn(
        TurnRequest(
            user_id=user_id,
            prompt=content,
            session_id=session_id,
            session_scope=SESSION_SCOPE_EXISTING,
            project_id=project_id or "",
            project_id_explicit=True,
            runtime_target_id=runtime_target_id or "",
            runtime_target_id_explicit=bool(str(runtime_target_id or "").strip()),
            thinking_level=thinking_level or "light",
            thinking_level_explicit=thinking_level is not None,
            agent_id=agent_id or "",
            agent_type=agent_type,
            workflow_key=workflow_key,
            workflow_decisions=workflow_decisions,
        ),
        session_factory=session_factory,
    )
    if isinstance(prepared, TurnRefusal):
        return prepared
    await run_request_turn(
        db, run_agent_func=run_agent_func, session_factory=session_factory, prepared=prepared, user_id=user_id
    )
    return await _turn_messages(db, session_id=prepared.session_id, user_message_id=prepared.user_message_id)


__all__ = ["build_dispatched_message_response", "send_session_message"]
