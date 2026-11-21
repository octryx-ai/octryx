"""Double-texting guard and message idempotency enforcement."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session
from ..services.session.run_state import RUN_STATUS_IN_PROGRESS, get_session_run_status, set_session_run_state

logger = logging.getLogger(__name__)

# Idempotency key header name
IDEMPOTENCY_KEY_HEADER = "X-Idempotency-Key"


class DoubleTextGuardError(Exception):
    """Raised when a second message arrives while a run is in progress."""

    def __init__(self, session_id: str, current_status: str):
        self.session_id = session_id
        self.current_status = current_status
        super().__init__(f"Session {session_id} is currently {current_status}; cannot start new turn")


class MessageIdempotencyError(Exception):
    """Raised when a message with a duplicate idempotency key is inserted."""

    def __init__(self, idempotency_key: str):
        self.idempotency_key = idempotency_key
        super().__init__(f"Message with idempotency key '{idempotency_key}' already exists")


async def check_double_text_guard(
    db: AsyncSession,
    session: Session,
) -> None:
    """Verify a new turn can safely start in this session.

    Raises DoubleTextGuardError if the session already has an in-progress run.
    """
    # Also sync run_status to DB column when checking
    current_run_status = get_session_run_status(session)
    # If metadata says in_progress, sync to DB column
    if current_run_status == RUN_STATUS_IN_PROGRESS and session.run_status != RUN_STATUS_IN_PROGRESS:
        session.run_status = RUN_STATUS_IN_PROGRESS
        await db.flush()

    if session.run_status == RUN_STATUS_IN_PROGRESS:
        raise DoubleTextGuardError(session.id, RUN_STATUS_IN_PROGRESS)

    if session.run_status and session.run_status not in {"completed", "error", "stopped", "cancelled", None}:
        logger.warning(
            "[double_text_guard] Session %s has run_status=%s (not in_progress) — proceeding with caution",
            session.id,
            session.run_status,
        )


async def mark_session_running(
    db: AsyncSession,
    session: Session,
) -> None:
    """Mark a session as in_progress — called when a turn starts."""
    session.run_status = RUN_STATUS_IN_PROGRESS
    set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
    await db.flush()


async def mark_session_complete(
    db: AsyncSession,
    session: Session,
    final_status: str = "completed",
) -> None:
    """Mark a session run as completed."""
    session.run_status = final_status
    set_session_run_state(session, final_status)
    await db.flush()


async def mark_session_failed(
    db: AsyncSession,
    session: Session,
    error: str | None = None,
) -> None:
    """Mark a session run as failed."""
    session.run_status = "error"
    set_session_run_state(session, "error")
    if error:
        metadata = dict(session.metadata_ or {})
        metadata["last_error"] = error
        session.metadata_ = metadata
    await db.flush()
