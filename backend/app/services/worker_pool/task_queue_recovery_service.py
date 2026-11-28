"""Recovery of TaskQueueEntry claims whose worker stopped heartbeating."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Staleness threshold: if no heartbeat for this many minutes, entry is orphan
DEFAULT_HEARTBEAT_STALE_MINUTES = 30


async def recover_stale_task_queue_entries(db: AsyncSession) -> int:
    from datetime import timedelta

    from ...models import TaskQueueEntry

    now = _utc_now()
    recovered = 0
    stale_threshold = timedelta(minutes=DEFAULT_HEARTBEAT_STALE_MINUTES)

    result = await db.execute(
        select(TaskQueueEntry).where(
            TaskQueueEntry.status == "in_progress",
            TaskQueueEntry.assigned_to.isnot(None),
        )
    )
    stale_entries = result.scalars().all()
    for entry in stale_entries:
        # Entry is orphan if: no heartbeat ever, OR heartbeat too old
        if entry.last_heartbeat is None:
            pass  # orphan — no heartbeat means unknown last activity
        elif now - entry.last_heartbeat <= stale_threshold:
            continue  # fresh — not stale, skip
        # If we get here: last_heartbeat is None OR expired
        entry.status = "pending"
        entry.assigned_to = None
        entry.assigned_at = None
        entry.started_at = None
        entry.last_heartbeat = None
        entry.timeout_minutes = None
        recovered += 1
        logger.info(
            "[queue_recovery] Recovered stalled task queue entry %s (assigned_to=%s, last_heartbeat=%s)",
            entry.id,
            entry.assigned_to,
            entry.last_heartbeat,
        )

    if recovered:
        await db.commit()
        logger.info("[queue_recovery] Total task queue entries recovered: %d", recovered)
    return recovered


def _utc_now():
    from ...time_utils import utc_now
    return utc_now()
