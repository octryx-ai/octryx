"""``/api/v1/sessions/{id}/messages``: one turn on a runner, answered with its messages from the user message on."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import core as db_core
from ...models import Message
from ...schemas.operations.session import MessageResponse
from ...time_utils import utc_isoformat
from .turn_handoff import held_by_gate, names_a_workflow, runner_turn_kwargs
from .turn_refusals import TurnRefusal
from .turn_request import SESSION_SCOPE_EXISTING, TurnRequest
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
    project_id: str | None = None,
    agent_type: str = "",
    workflow_key: str = "",
    workflow_decisions: dict[str, str] | None = None,
    runtime_target_id: str | None = None,
    thinking_level: str | None = None,
    agent_id: str | None = None,
    session_factory=None,
    person_chat: bool = False,
) -> list[MessageResponse] | TurnRefusal:
    from ..devices.agent_runtime import chat_target_for

    session_factory = session_factory or db_core.async_session_factory
    if not names_a_workflow(workflow_key, workflow_decisions):
        from .turn_project_scope import load_writable_turn_session
        from .turn_refusals import TurnRefusedError

        try:
            await load_writable_turn_session(db, user_id=user_id, session_id=session_id)
        except TurnRefusedError as refused:
            return refused.refusal
        return await _pool_turn(db, session_id=session_id, content=content, user_id=user_id,
                                target=await chat_target_for(db, session_id), person_chat=person_chat)
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
    if await held_by_gate(db, prepared, session_factory=session_factory):
        return await _turn_messages(db, session_id=prepared.session_id, user_message_id=prepared.user_message_id)
    handoff = await runner_turn_kwargs(db, prepared)
    return await _pool_turn(db, session_id=prepared.session_id, content=prepared.prompt, user_id=user_id,
                            target=handoff["target"], rerun_message=handoff["rerun_message"], person_chat=person_chat)


async def _pool_turn(db: AsyncSession, *, session_id: str, content: str, user_id: str, target: dict,
                     rerun_message=None, person_chat: bool = False) -> list[MessageResponse]:
    from fastapi import HTTPException

    from ..devices.agent_runtime import run_pool_turn
    from ..devices.chat_turn import DeviceTurnRefusal

    turn = await run_pool_turn(db, user_id=user_id, prompt=content, session_id=session_id, target=target,
                               rerun_message=rerun_message, person_chat=person_chat)
    if isinstance(turn, DeviceTurnRefusal):
        raise HTTPException(status_code=turn.status, detail=turn.detail())
    return await _turn_messages(db, session_id=turn.session_id, user_message_id=turn.user_message_id)


__all__ = ["build_dispatched_message_response", "send_session_message"]
