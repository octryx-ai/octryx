"""Start a turn: prepare it, then the execution gate holds it or hands it to a runner."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import core as db_core
from ...db.lock_errors import is_sqlite_lock_error
from ...models import DeviceJob, User
from ...models import Session as AgentSession
from . import turn_prepare
from .turn_handoff import held_by_gate, runner_turn_kwargs
from .turn_refusals import TurnRefusal, TurnRefusalState, TurnRefusedError
from .turn_request import PreparedTurn, TurnRequest

logger = logging.getLogger(__name__)

# Serializes turn preparation in this process (SQLite has one writer).
TURN_PREPARE_LOCK = asyncio.Lock()
PREPARE_ATTEMPTS = 5


async def prepare_turn(request: TurnRequest, *, session_factory=None) -> PreparedTurn | TurnRefusal:
    session_factory = session_factory or db_core.async_session_factory
    async with TURN_PREPARE_LOCK:
        for attempt in range(PREPARE_ATTEMPTS):
            try:
                async with session_factory() as db:
                    user = await db.get(User, request.user_id)
                    if user is None:
                        return TurnRefusal(TurnRefusalState.USER_NOT_FOUND, "User not found")
                    return await turn_prepare.prepare_turn_in_session(
                        db, user=user, request=request
                    )
            except TurnRefusedError as refused:
                return refused.refusal
            except OperationalError as exc:
                if not is_sqlite_lock_error(exc) or attempt == PREPARE_ATTEMPTS - 1:
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
    from ..devices.chat_turn import DeviceTurnRefusal, start_device_turn
    from ..devices.jobs_channel import publish

    session_factory = session_factory or db_core.async_session_factory
    prepared = await prepare_turn(request, session_factory=session_factory)
    if isinstance(prepared, TurnRefusal):
        return prepared
    async with session_factory() as db:
        if await held_by_gate(db, prepared, session_factory=session_factory):
            return prepared
        started = await start_device_turn(db, user_id=request.user_id, wait_for_runner=True,
                                          **await runner_turn_kwargs(db, prepared))
        if isinstance(started, DeviceTurnRefusal):
            return TurnRefusal(TurnRefusalState.RUNNER_REFUSED, started.detail())
        await db.commit()
        await publish(await db.get(DeviceJob, started.job_id), {"eventType": "turn_offered"})
    return prepared


async def load_prepared_session(db: AsyncSession, prepared: PreparedTurn) -> AgentSession | None:
    session = await db.get(AgentSession, prepared.session_id)
    if session is None:
        await db.rollback()
        session = await db.get(AgentSession, prepared.session_id)
    return session


__all__ = ["PREPARE_ATTEMPTS", "TURN_PREPARE_LOCK", "load_prepared_session", "prepare_turn", "start_turn"]
