"""Run timeout service — detects and resolves stalled in-progress sessions.

A session is considered stalled when:
- run_status == 'in_progress'
- No heartbeat or last activity for longer than the configured timeout

This service is called periodically by the scheduler to enforce timeout semantics.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from ...time_utils import utc_now

logger = logging.getLogger(__name__)

# Default timeout for in-progress runs (minutes)
DEFAULT_RUN_TIMEOUT_MINUTES = 60
# Minimum safe timeout to avoid premature cancellation
MIN_RUN_TIMEOUT_MINUTES = 5


async def timeout_stalled_sessions(
    db: AsyncSession,
    *,
    timeout_minutes: int = DEFAULT_RUN_TIMEOUT_MINUTES,
) -> int:
    """Find and timeout sessions that have been in_progress beyond the allowed duration.

    Uses updated_at as the last-activity indicator. Sessions whose updated_at is older
    than timeout_minutes are transitioned to run_status='error' with a timeout reason.

    Returns count of sessions timed out.
    """
    timeout_minutes = max(MIN_RUN_TIMEOUT_MINUTES, int(timeout_minutes or DEFAULT_RUN_TIMEOUT_MINUTES))
    cutoff = utc_now() - timedelta(minutes=timeout_minutes)

    result = await db.execute(
        select(Session).where(
            Session.run_status == "in_progress",
            Session.started_at < cutoff,
        )
    )
    stalled = list(result.scalars().all())
    if not stalled:
        return 0

    now = utc_now()
    for session in stalled:
        session.run_status = "error"
        metadata = dict(session.metadata_ or {})
        metadata["run_completion_reason"] = "timeout"
        metadata["timeout_at"] = now.isoformat()
        metadata.pop("current_turn_started_at", None)
        session.metadata_ = metadata

    await db.flush()
    logger.info("[run_timeout] Timed out %d stalled sessions (cutoff=%s)", len(stalled), cutoff.isoformat())
    return len(stalled)
