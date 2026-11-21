"""Start a marked chat turn as a registered background task.

Every background turn start goes through :func:`launch_chat_turn`: a prepared turn
(``turn_start.start_turn``: ``/chat/api`` send and continue, coordinator continue,
sub-agent resume, coding execution), a rerun (:func:`start_chat_rerun_turn`) and an
approval resume (``approval_resume``). The task runs ``turn_runner.run_chat_turn`` and is
registered in ``turn_tasks.CHAT_RUN_TASKS``, so stop, the "running" state and the
test harness see one registry.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message
from ...models import Session as AgentSession
from ..agent_definition_execution import resolve_agent_definition_for_execution
from ..agent_definition_execution_outcomes import execution_payload_or_none
from ..chat_rerun import prepare_chat_rerun
from ..request_context import get_current_request_id
from .turn_runner import run_chat_turn
from .turn_tasks import register_turn_task

logger = logging.getLogger(__name__)


def launch_chat_turn(
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
) -> asyncio.Task:
    """Run the turn marked on ``session_id`` in the background, as ``user_id``."""
    task = asyncio.create_task(
        run_chat_turn(
            session_factory=session_factory,
            session_id=session_id,
            user_id=user_id,
            prompt=prompt,
            project_id=project_id,
            agent_type=agent_type,
            runtime_target_id=runtime_target_id,
            thinking_level=thinking_level,
            agent_definition=agent_definition,
            request_id=get_current_request_id(),
        )
    )
    logger.info(
        "chat.turn.task_created",
        extra={
            "session_id": session_id,
            "project_id": project_id,
            "agent_type": agent_type,
            "runtime_target_id": runtime_target_id,
        },
    )

    def _log_task_done(done_task: asyncio.Task) -> None:
        if done_task.cancelled():
            logger.info("chat.turn.task_done.cancelled", extra={"session_id": session_id})
            return
        exc = done_task.exception()
        if exc is not None:
            logger.exception("chat.turn.task_done.error", exc_info=exc, extra={"session_id": session_id})
            return
        logger.info("chat.turn.task_done.ok", extra={"session_id": session_id})

    task.add_done_callback(_log_task_done)
    register_turn_task(session_id, task)
    return task


async def resolve_turn_agent_definition(db: AsyncSession, metadata: dict, *, owner_id: str) -> dict | None:
    """The session's selected agent, resolved explicitly: a published revision or the named draft."""
    selected_agent_id = str(metadata.get("agent_definition_id") or "").strip()
    if not selected_agent_id:
        return None
    return execution_payload_or_none(
        await resolve_agent_definition_for_execution(db, definition_id=selected_agent_id, visible_to_user_id=owner_id)
    )


async def start_chat_rerun_turn(
    db: AsyncSession,
    *,
    user_id: str,
    session_factory,
    session: AgentSession,
    message: Message,
    prompt: str,
) -> AgentSession:
    """Rewind ``session`` to ``message``, mark it as the turn and run it again.

    The session's agent is resolved first: a refused one (inactive, unpublished, ...) answers
    the 409 before the rewind deletes any later history.
    """
    agent_definition = await resolve_turn_agent_definition(db, dict(session.metadata_ or {}), owner_id=user_id)
    prepared = await prepare_chat_rerun(db, session=session, target_message=message, prompt=prompt)
    metadata = dict(prepared.session.metadata_ or {})
    launch_chat_turn(
        session_factory=session_factory,
        session_id=prepared.session.id,
        user_id=user_id,
        prompt=prepared.prompt,
        project_id=prepared.session.project_id,
        agent_type=prepared.session.agent_type,
        runtime_target_id=str(metadata.get("runtime_target_id") or "").strip() or None,
        thinking_level=str(metadata.get("thinking_level") or "light").strip() or "light",
        agent_definition=agent_definition,
    )
    return prepared.session


__all__ = ["launch_chat_turn", "resolve_turn_agent_definition", "start_chat_rerun_turn"]
