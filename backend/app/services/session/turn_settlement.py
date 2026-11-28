"""The completion step of a prepared chat turn: clear the turn marker, settle the session and run state."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .stream import session_stream_manager
from .turn_completion import ChatTurnCompletionResult, finalize_chat_turn_after_agent_stream
from .turn_event_payloads import approval_request_payload, run_state_payload
from .turn_follow_up import schedule_completion_follow_up

logger = logging.getLogger(__name__)


async def publish_agent_event(session_id: str, event: Any) -> None:
    role = getattr(event, "role", None)
    content = getattr(event, "content", None)
    if role == "assistant" and content:
        await session_stream_manager.publish(
            session_id,
            "agent_message",
            {"role": role, "content": content, "model": getattr(event, "model", None)},
        )
    elif role == "tool":
        await session_stream_manager.publish(session_id, "tool_call", {"role": role, "content": content})


async def settle_turn_after_stream(
    db: AsyncSession,
    *,
    session_id: str,
    session_factory,
    request_id: str | None,
) -> ChatTurnCompletionResult:
    result = await finalize_chat_turn_after_agent_stream(db, session_id=session_id)
    await db.commit()
    if result.session_status == "pending_approval":
        await session_stream_manager.publish(session_id, "approval_request", approval_request_payload())
    else:
        await session_stream_manager.publish(
            session_id,
            "run_state",
            run_state_payload(run_status=result.run_status, run_completion_reason=result.run_completion_reason),
        )
    if result.completion_follow_up is not None:
        schedule_completion_follow_up(
            session_factory=session_factory,
            session_id=session_id,
            request_id=request_id,
            completion_follow_up=result.completion_follow_up,
        )
    await _workflow_turn_ended(session_id, failed=False, session_factory=session_factory)
    return result


async def _workflow_turn_ended(session_id: str, *, failed: bool, session_factory) -> None:
    from ..workflow_runs.server_continuation import server_turn_ended

    try:
        await server_turn_ended(session_id, failed=failed, session_factory=session_factory)
    except Exception:  # noqa: BLE001 - the chat turn is settled; the run shows its own state
        logger.warning("workflow_run.server_turn_ended_failed session_id=%s", session_id, exc_info=True)


__all__ = ["publish_agent_event", "settle_turn_after_stream", "workflow_turn_failed"]


async def workflow_turn_failed(*, session_factory, session_id: str) -> None:
    await _workflow_turn_ended(session_id, failed=True, session_factory=session_factory)
