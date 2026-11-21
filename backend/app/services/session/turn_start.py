"""Start a turn: the one entry of both session paths into turn preparation.

* :func:`prepare_turn` resolves the workflow proposal before the process-global
  :data:`TURN_PREPARE_LOCK` (a governed model call must never hold it), after admitting
  the turn's agent (a directly chosen agent skips it, a refused one makes no call), then
  prepares the turn under the lock in its own database session, retrying a locked SQLite
  writer. It answers a committed, marked :class:`PreparedTurn` or a closed
  :class:`TurnRefusal`; it never raises an HTTP error.
* :func:`start_turn` prepares and launches the turn as a registered background task
  (``turn_launch``): ``/chat/api`` and the services that start a chat turn (coordinator
  continue, sub-agent resume, coding execution).

``/api/v1`` prepares with :func:`prepare_turn` and runs the turn inside its request
(``message_dispatch``).
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.core.execution_support import _is_sqlite_lock_error
from ...db import core as db_core
from ...models import Session as AgentSession
from ...models import User
from ..workflow_routing.proposal_prefetch import prefetch_workflow_proposal
from ..workflow_routing.proposal_states import WORKFLOW_KEY_NONE
from . import turn_prepare
from .turn_launch import launch_chat_turn
from .turn_refusals import TurnRefusal, TurnRefusalState, TurnRefusedError
from .turn_request import PreparedTurn, TurnRequest

logger = logging.getLogger(__name__)

# Serializes turn preparation in this process (SQLite has one writer).
TURN_PREPARE_LOCK = asyncio.Lock()
PREPARE_ATTEMPTS = 5


def _prefetch_workflow_key(request: TurnRequest) -> str:
    """The key the proposal prefetch sees: a platform service's own workflow makes no proposal call."""
    if request.platform_workflow_service:
        return WORKFLOW_KEY_NONE
    return request.workflow_key.strip()


async def prepare_turn(request: TurnRequest, *, session_factory=None) -> PreparedTurn | TurnRefusal:
    session_factory = session_factory or db_core.async_session_factory
    precomputed_proposal = await prefetch_workflow_proposal(
        session_factory,
        user_id=request.user_id,
        prompt=request.prompt,
        session_id=request.session_id,
        session_scope=request.session_scope,
        project_id=request.project_id,
        workflow_key=_prefetch_workflow_key(request),
        agent_id=request.agent_id,
        agent_type_explicit=request.agent_type_explicit,
    )
    async with TURN_PREPARE_LOCK:
        for attempt in range(PREPARE_ATTEMPTS):
            try:
                async with session_factory() as db:
                    user = await db.get(User, request.user_id)
                    if user is None:
                        return TurnRefusal(TurnRefusalState.USER_NOT_FOUND, "User not found")
                    return await turn_prepare.prepare_turn_in_session(
                        db, user=user, request=request, precomputed_proposal=precomputed_proposal
                    )
            except TurnRefusedError as refused:
                return refused.refusal
            except OperationalError as exc:
                if not _is_sqlite_lock_error(exc) or attempt == PREPARE_ATTEMPTS - 1:
                    raise
                logger.warning(
                    "chat.turn.prepare.lock_retry",
                    extra={
                        "user_id": request.user_id,
                        "session_id": request.session_id or None,
                        "attempt": attempt + 1,
                    },
                )
                await asyncio.sleep(0.25 * (attempt + 1))
    return TurnRefusal(TurnRefusalState.PREPARATION_FAILED, "Unable to prepare chat turn")


async def start_turn(request: TurnRequest, *, session_factory=None) -> PreparedTurn | TurnRefusal:
    """Prepare the turn and run it in the background; the refusal when it may not start."""
    session_factory = session_factory or db_core.async_session_factory
    prepared = await prepare_turn(request, session_factory=session_factory)
    if isinstance(prepared, TurnRefusal):
        return prepared
    launch_chat_turn(
        session_factory=session_factory,
        session_id=prepared.session_id,
        user_id=request.user_id,
        prompt=prepared.prompt,
        project_id=prepared.project_id,
        agent_type=prepared.agent_type,
        runtime_target_id=prepared.runtime_target_id,
        thinking_level=prepared.thinking_level,
        agent_definition=prepared.agent_definition,
    )
    return prepared


async def load_prepared_session(db: AsyncSession, prepared: PreparedTurn) -> AgentSession | None:
    """The prepared session in the caller's database session (a stale snapshot is rolled back once)."""
    session = await db.get(AgentSession, prepared.session_id)
    if session is None:
        await db.rollback()
        session = await db.get(AgentSession, prepared.session_id)
    return session


__all__ = ["PREPARE_ATTEMPTS", "TURN_PREPARE_LOCK", "load_prepared_session", "prepare_turn", "start_turn"]
