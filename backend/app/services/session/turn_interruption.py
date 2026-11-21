"""Settle ``running`` chat sessions whose owning process died.

A session is ``running`` only while the process named in ``turn_owner_process_id``
executes its turn. When that process has no live lease, the turn can never finish,
so the session is returned to idle (``active``) with an explicit, readable cause:
run status ``failed``, completion and stop reason ``interrupted_by_restart``.

Only ``running`` is settled. ``pending_approval``, ``awaiting_subagents`` and every
other status is left exactly as it is, so a paused turn stays resumable. The move is
a compare-and-set on ``(status, owner)``: a turn a live process started in between
is never settled.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from ..runtime_ownership.process_lease import live_process_ids
from .run_state import RUN_STATUS_FAILED, RUN_STATUS_IN_PROGRESS, set_session_run_state
from .turn_approval_state import end_chat_turn

SESSION_STATUS_RUNNING = "running"
SESSION_STATUS_IDLE = "active"
INTERRUPTED_BY_RESTART = "interrupted_by_restart"
# The ``Session.run_status`` column (the double-text guard's) uses its own vocabulary for a failed run.
_COLUMN_RUN_STATUS_FAILED = "error"


async def settle_orphaned_running_sessions(db: AsyncSession) -> list[Session]:
    """Return every ``running`` session without a live owner to idle; returns the settled rows."""
    running = list(
        (await db.execute(select(Session).where(Session.status == SESSION_STATUS_RUNNING))).scalars().all()
    )
    if not running:
        return []
    live = await live_process_ids(db, (session.turn_owner_process_id for session in running))
    settled: list[Session] = []
    for session in running:
        owner = session.turn_owner_process_id
        if owner in live:
            continue
        owner_column = Session.turn_owner_process_id
        owner_matches = owner_column.is_(None) if owner is None else owner_column == owner
        moved = await db.execute(
            update(Session)
            .where(Session.id == session.id, Session.status == SESSION_STATUS_RUNNING, owner_matches)
            .values(status=SESSION_STATUS_IDLE)
            .execution_options(synchronize_session=False)
        )
        if int(moved.rowcount or 0) != 1:
            continue
        _record_interruption(session)
        settled.append(session)
    await db.flush()
    return settled


def _record_interruption(session: Session) -> None:
    session.status = SESSION_STATUS_IDLE
    if session.run_status == RUN_STATUS_IN_PROGRESS:
        session.run_status = _COLUMN_RUN_STATUS_FAILED
    metadata = dict(session.metadata_ or {})
    metadata["last_stop_reason"] = INTERRUPTED_BY_RESTART
    metadata.pop("run_started_at", None)
    end_chat_turn(metadata)
    session.metadata_ = metadata
    set_session_run_state(session, RUN_STATUS_FAILED, INTERRUPTED_BY_RESTART)


__all__ = ["INTERRUPTED_BY_RESTART", "settle_orphaned_running_sessions"]
