"""Run one chat turn: announce it, stream the agent, and settle the turn.

Two runners share every step after the entry path marked the turn (``begin_chat_turn``):

* :func:`run_chat_turn` is the background task of ``/chat/api`` (send, rerun, thread
  continuation) and of an approval resume. It owns its database sessions and ends the task
  quietly after settling a failure;
* :func:`run_request_turn` runs a ``/api/v1/sessions/{id}/messages`` turn inside the
  request, as a task registered in ``CHAT_RUN_TASKS`` (so it reads ``running`` and stops
  through ``turn_stop``). It returns the agent events and whether the turn was stopped,
  and re-raises a failure after settling it.

Both publish ``turn_started``, mirror agent events onto the session stream, finish with
``turn_settlement.settle_turn_after_stream`` and settle a cancelled or failed turn
with ``turn_failure``. Both bind the turn's Product Run with ``run_origin="chat_turn"``.

``run_agent`` is imported here so tests replace the agent at this owner.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.engine import run_agent
from ...models import Session as AgentSession
from ...models.runtime.product_run import RUN_ORIGIN_CHAT_TURN
from ..request_context import get_current_request_id, reset_current_request_id, set_current_request_id
from .runtime_events import publish_turn_started
from .turn_approval_state import CURRENT_TURN_USER_MESSAGE_KEY
from .turn_failure import settle_cancelled_turn, settle_failed_turn
from .turn_request import PreparedTurn
from .turn_settlement import publish_agent_event, settle_turn_after_stream, workflow_turn_failed
from .turn_tasks import register_turn_task, release_turn_task

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RequestTurnOutcome:
    events: list[Any]
    stopped: bool


async def run_chat_turn(
    *,
    session_factory,
    session_id: str,
    user_id: str,
    prompt: str,
    project_id: str | None,
    agent_type: str,
    runtime_target_id: str | None,
    thinking_level: str,
    agent_definition: dict | None,
    request_id: str | None,
) -> None:
    request_token = set_current_request_id(request_id) if request_id else None
    try:
        await asyncio.sleep(0.2)
        logger.info(
            "chat.turn.start",
            extra={
                "session_id": session_id,
                "project_id": project_id,
                "agent_type": agent_type,
                "runtime_target_id": runtime_target_id,
            },
        )
        async with session_factory() as db:
            session = await db.get(AgentSession, session_id)
            turn_metadata = dict(session.metadata_ or {}) if session else {}
            await publish_turn_started(
                session_id=session_id,
                turn_id=request_id or get_current_request_id(),
                user_message_id=str(turn_metadata.get(CURRENT_TURN_USER_MESSAGE_KEY) or "") or None,
                project_id=project_id,
                agent_type=agent_type,
                runtime_target_id=runtime_target_id,
                thinking_level=thinking_level,
                request_id=request_id or get_current_request_id(),
            )
            async for event in run_agent(
                session_id=session_id,
                user_message=prompt,
                user_id=user_id,
                project_id=project_id,
                agent_type=agent_type,
                db=db,
                runtime_target_id=runtime_target_id,
                thinking_level=thinking_level,
                agent_definition=agent_definition,
                run_origin=RUN_ORIGIN_CHAT_TURN,
            ):
                await publish_agent_event(session_id, event)
            logger.info("chat.turn.agent_stream_complete", extra={"session_id": session_id})
            await settle_turn_after_stream(
                db, session_id=session_id, session_factory=session_factory, request_id=request_id
            )
    except asyncio.CancelledError:
        logger.info("chat.turn.cancelled", extra={"session_id": session_id})
        await settle_cancelled_turn(session_factory=session_factory, session_id=session_id)
        raise
    except Exception as exc:
        logger.exception("chat.turn.failed", extra={"session_id": session_id})
        await settle_failed_turn(session_factory=session_factory, session_id=session_id, prompt=prompt, exc=exc)
        await workflow_turn_failed(session_factory=session_factory, session_id=session_id)
    finally:
        if request_token is not None:
            reset_current_request_id(request_token)
        release_turn_task(session_id, asyncio.current_task())


async def run_request_turn(
    db: AsyncSession,
    *,
    run_agent_func: Callable[..., Any] | None,
    session_factory,
    prepared: PreparedTurn,
    user_id: str,
) -> RequestTurnOutcome:
    """Run a prepared turn inside the request as a registered task; returns its outcome.

    The task is registered in ``CHAT_RUN_TASKS`` like a background turn, so the session
    reads ``running`` while it runs and ``turn_stop`` cancels it through the same path.
    A stopped turn is settled ``stopped`` and answered as such; a failure is settled and
    re-raised; a cancelled request cancels the turn.
    """
    request_id = get_current_request_id()
    session_id = prepared.session_id
    # Preparation committed the turn in its own database session: the request's copy of the
    # session row (if it holds one) is stale and must not be settled over the prepared state.
    request_copy = await db.get(AgentSession, session_id)
    if request_copy is not None:
        await db.refresh(request_copy)
    await publish_turn_started(
        session_id=session_id,
        turn_id=request_id,
        user_message_id=prepared.user_message_id,
        project_id=prepared.project_id,
        agent_type=prepared.agent_type,
        runtime_target_id=prepared.runtime_target_id,
        thinking_level=prepared.thinking_level,
        request_id=request_id,
    )
    events: list[Any] = []
    agent_stream = run_agent_func or run_agent

    async def stream_and_settle() -> None:
        try:
            async for event in agent_stream(
                session_id=session_id,
                user_message=prepared.prompt,
                user_id=user_id,
                project_id=prepared.project_id,
                agent_type=prepared.agent_type,
                db=db,
                runtime_target_id=prepared.runtime_target_id,
                thinking_level=prepared.thinking_level,
                agent_definition=prepared.agent_definition,
                run_origin=RUN_ORIGIN_CHAT_TURN,
            ):
                events.append(event)
                await publish_agent_event(session_id, event)
            await settle_turn_after_stream(
                db, session_id=session_id, session_factory=session_factory, request_id=request_id
            )
        except asyncio.CancelledError:
            await db.rollback()
            await settle_cancelled_turn(session_factory=session_factory, session_id=session_id)
            raise
        except Exception as exc:
            logger.exception("chat.turn.failed", extra={"session_id": session_id})
            await db.rollback()
            await settle_failed_turn(
                session_factory=session_factory, session_id=session_id, prompt=prepared.prompt, exc=exc
            )
            await workflow_turn_failed(session_factory=session_factory, session_id=session_id)
            raise

    task = asyncio.create_task(stream_and_settle())
    register_turn_task(session_id, task)
    try:
        await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if not task.cancelled() or (current is not None and current.cancelling()):
            raise
        # Stopped through turn_stop while the request waited: the turn settled as stopped.
        return RequestTurnOutcome(events=events, stopped=True)
    finally:
        release_turn_task(session_id, task)
    return RequestTurnOutcome(events=events, stopped=False)


__all__ = ["RequestTurnOutcome", "run_chat_turn", "run_request_turn"]
