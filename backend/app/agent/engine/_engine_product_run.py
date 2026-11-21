"""Product Run scope around one Chat turn at the execution boundary.

``run_agent`` enters :class:`ProductRunScope` for every turn. Only a caller that
passes an explicit ``run_origin`` binds the turn (the Chat entry points pass
``"chat_turn"``; a sub-agent group's child turns pass ``"sub_agent"`` and the scheduler
passes ``"scheduled_task"``); every other caller gets an inert scope with no stamp, no
rows and no commits. Nothing is inferred from message content.

A bound turn:

* resolves its Workspace from the session row (Workspace = the session's project).
  A session without a project opens no run and is stamped ``unscoped``, since a
  run always belongs to a Workspace;
* otherwise opens a new run (each ``run_agent`` call is a new run) in ``requested``
  and stamps its identity into the turn execution snapshot;
* records the admission (``admitted`` and ``running``, or the gate's blocked state,
  or ``needs_configuration`` for a readiness block) and, when the turn ends, its
  terminal state: see ``services/product_run/turn_outcome.py`` for the closed
  mapping, plus the exception table below.

Exit by exception (the exception always propagates unchanged):

* ``GeneratorExit`` (``aclose``)      -> ``cancelled`` / ``generator_closed``
* ``asyncio.CancelledError``          -> ``cancelled`` / ``task_cancelled``
* ``ProviderRuntimeError`` (running)  -> ``failed`` / ``provider_error``
* any other exception in ``requested``  -> ``failed`` / ``preparation_failed``
* any other exception later           -> ``failed`` / ``runtime_exception``

Failure policy. A run that cannot be *opened* fails the turn closed with
:class:`ProductRunUnavailableError` (fixed message and code; no model call, no tool).
Any later bookkeeping failure never changes the assistant output or tool behaviour:
it is logged once as ``product_run.bookkeeping_failed`` with a fixed error code, and
the scope records nothing further for that turn (the attempt keeps its last stored
state; reconciliation is Track 6 follow-up work).

Writes use the turn's own session and are committed right away: the run must be
visible while the turn runs, and the loop commits on the same session. On an
exception or cancellation exit the turn's uncommitted work is rolled back first
(the caller discards it anyway), so the terminal write never commits a half-done
step. The terminal write is shielded, so a repeated cancellation cannot abort it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from types import TracebackType
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.product_run.errors import ProductRunError

from ...models import Session as ChatSession
from ...models.runtime.product_run import (
    RUN_ORIGINS,
    RUN_STATE_CANCELLED,
    RUN_STATE_FAILED,
    RUN_STATE_REQUESTED,
    RUN_STATE_RUNNING,
)
from ...services.knowledge.identity.workspace import WorkspaceId
from ...services.knowledge.retrieval.errors import InvalidWorkspaceError
from ...services.product_run.service import ProductRunHandle, open_run, transition
from ...services.product_run.states import ACTIVE_STATES
from ...services.product_run.turn_outcome import (
    READINESS_BLOCK_MOVE,
    RunMove,
    gate_move,
    load_turn_end_move,
)
from ...services.product_run.turn_stamp import bound_stamp, unscoped_stamp
from ...time_utils import utc_now
from ..core.runtime.runtime_errors import ProviderRuntimeError
from ._engine_turn_admission import TURN_ADMITTED, TURN_BLOCKED_BY_EXECUTION_GATE, TurnAdmission

logger = logging.getLogger(__name__)

# ``open_run`` always opens the run with its first attempt.
_FIRST_ATTEMPT_NUMBER = 1
_BOOKKEEPING_DATABASE_ERROR = "database_error"
_BOOKKEEPING_GATE_UNMAPPED = "gate_decision_unmapped"


class ProductRunUnavailableError(RuntimeError):
    """The Chat turn could not be opened as a Product Run; it was not executed."""

    code = "product_run_unavailable"

    def __init__(self) -> None:
        super().__init__("This request was not executed because its run could not be recorded.")


def _canonical_message_id(value: Any) -> str | None:
    # The turn's user message id is recorded only in canonical form; anything else is omitted.
    if not isinstance(value, str):
        return None
    try:
        return value if str(uuid.UUID(value)) == value else None
    except ValueError:
        return None


class ProductRunScope:
    """Async context manager owning one turn's Product Run bookkeeping."""

    def __init__(self, db: AsyncSession, *, session_id: str, origin: str | None) -> None:
        self._db = db
        self._session_id = str(session_id)
        self._origin = origin
        self._handle: ProductRunHandle | None = None
        self._opened_at: datetime | None = None
        self._failed_code: str | None = None
        self.stamp: dict[str, Any] | None = None

    @property
    def handle(self) -> ProductRunHandle | None:
        return self._handle

    def _recording(self) -> bool:
        return self._handle is not None and self._failed_code is None and self._handle.state in ACTIVE_STATES

    def _refuse(self, code: str) -> ProductRunUnavailableError:
        logger.error("product_run.open_refused", extra={"session_id": self._session_id, "error_code": code})
        return ProductRunUnavailableError()

    async def __aenter__(self) -> ProductRunScope:
        if self._origin is None:
            return self
        if self._origin not in RUN_ORIGINS:
            raise self._refuse("invalid_origin")
        try:
            row = (
                await self._db.execute(
                    select(ChatSession.user_id, ChatSession.project_id, ChatSession.metadata_).where(
                        ChatSession.id == self._session_id
                    )
                )
            ).one_or_none()
        except SQLAlchemyError as exc:
            raise self._refuse(type(exc).__name__) from None
        if row is None or not row.project_id:
            self.stamp = unscoped_stamp(origin=self._origin)
            logger.info("product_run.unscoped", extra={"session_id": self._session_id, "origin": self._origin})
            return self
        metadata = row.metadata_ if isinstance(row.metadata_, dict) else {}
        opened_at = utc_now()
        try:
            handle = await open_run(
                self._db,
                workspace_id=WorkspaceId.parse(row.project_id),
                owner_user_id=row.user_id,
                session_id=self._session_id,
                origin=self._origin,
                turn_user_message_id=_canonical_message_id(metadata.get("current_turn_user_message_id")),
            )
            await self._db.commit()
        except (ProductRunError, InvalidWorkspaceError, SQLAlchemyError) as exc:
            raise self._refuse(exc.code if isinstance(exc, ProductRunError) else type(exc).__name__) from None
        self._handle = handle
        self._opened_at = opened_at
        self.stamp = bound_stamp(
            run_id=handle.run_id,
            attempt_id=handle.attempt_id,
            attempt_number=_FIRST_ATTEMPT_NUMBER,
            origin=self._origin,
        )
        return self

    def _record_failure(self, code: str) -> None:
        self._failed_code = code
        logger.error(
            "product_run.bookkeeping_failed",
            extra={
                "session_id": self._session_id,
                "run_id": self._handle.run_id if self._handle else None,
                "state": self._handle.state if self._handle else None,
                "error_code": code,
            },
        )

    async def _move(self, move: RunMove) -> bool:
        if not self._recording():
            return False
        try:
            self._handle = await transition(
                self._db,
                self._handle,
                to_state=move.to_state,
                end_reason=move.end_reason,
                gate=move.gate,
            )
        except ProductRunError as exc:
            self._record_failure(exc.code)
            return False
        except SQLAlchemyError:
            self._record_failure(_BOOKKEEPING_DATABASE_ERROR)
            return False
        return True

    async def _commit(self) -> None:
        if self._handle is None or self._failed_code is not None:
            return
        try:
            await self._db.commit()
        except SQLAlchemyError:
            self._record_failure(_BOOKKEEPING_DATABASE_ERROR)

    async def record_admission(self, admission: TurnAdmission) -> None:
        """Record the gate decision and, for an admitted turn, readiness and the start of the loop."""
        if not self._recording():
            return
        decided = gate_move(admission.gate, admission.execution_profile)
        if decided is None:
            self._record_failure(_BOOKKEEPING_GATE_UNMAPPED)
            return
        if await self._move(decided) and admission.outcome != TURN_BLOCKED_BY_EXECUTION_GATE:
            await self._move(RunMove(RUN_STATE_RUNNING) if admission.outcome == TURN_ADMITTED else READINESS_BLOCK_MOVE)
        await self._commit()

    def _exception_move(self, exc: BaseException) -> RunMove:
        if isinstance(exc, GeneratorExit):
            return RunMove(RUN_STATE_CANCELLED, "generator_closed")
        if isinstance(exc, asyncio.CancelledError):
            return RunMove(RUN_STATE_CANCELLED, "task_cancelled")
        state = self._handle.state if self._handle else None
        if isinstance(exc, ProviderRuntimeError) and state == RUN_STATE_RUNNING:
            return RunMove(RUN_STATE_FAILED, "provider_error")
        return RunMove(RUN_STATE_FAILED, "preparation_failed" if state == RUN_STATE_REQUESTED else "runtime_exception")

    async def _terminal_write(self, exc: BaseException | None) -> None:
        if exc is None:
            if self._handle.state != RUN_STATE_RUNNING:
                return
            try:
                move = await load_turn_end_move(
                    self._db,
                    session_id=self._session_id,
                    run_id=self._handle.run_id,
                    attempt_id=self._handle.attempt_id,
                    opened_at=self._opened_at,
                )
            except SQLAlchemyError:
                self._record_failure(_BOOKKEEPING_DATABASE_ERROR)
                return
        else:
            move = self._exception_move(exc)
            if not isinstance(exc, GeneratorExit):
                # The caller discards the failed turn's uncommitted work; never commit a half-done step.
                try:
                    await self._db.rollback()
                except SQLAlchemyError:
                    self._record_failure(_BOOKKEEPING_DATABASE_ERROR)
                    return
        if await self._move(move):
            await self._commit()

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> bool:
        if not self._recording():
            return False
        write = asyncio.ensure_future(self._terminal_write(exc))
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            # A further cancellation while the terminal write runs: the write continues.
            logger.warning(
                "product_run.terminal_write_outlived_cancellation",
                extra={"session_id": self._session_id, "run_id": self._handle.run_id},
            )
            if not isinstance(exc, asyncio.CancelledError):
                raise
        except Exception as write_error:  # noqa: BLE001 - bookkeeping must never replace the turn's own outcome
            self._record_failure(type(write_error).__name__)
        return False


__all__ = ["ProductRunScope", "ProductRunUnavailableError"]
