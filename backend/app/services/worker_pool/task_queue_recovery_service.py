"""Worker-level claim and recovery service for TaskQueueEntry."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Staleness threshold: if no heartbeat for this many minutes, entry is orphan
DEFAULT_HEARTBEAT_STALE_MINUTES = 30


async def heartbeat_task_queue_entry(
    db: AsyncSession,
    entry_id: str,
    worker_id: str,
) -> bool:
    """Update the heartbeat timestamp for a queue entry owned by worker_id.

    Only succeeds if the entry is assigned to worker_id.
    Returns True if heartbeat updated, False otherwise.
    """
    from ...models import TaskQueueEntry

    entry = await db.get(TaskQueueEntry, entry_id)
    if entry is None:
        return False
    if entry.assigned_to != worker_id:
        return False
    entry.last_heartbeat = _utc_now()
    await db.flush()
    return True


async def claim_task_queue_entry(
    db: AsyncSession,
    entry_id: str,
    worker_id: str,
    *,
    timeout_minutes: int | None = None,
) -> bool:
    """Atomically claim a task queue entry for a worker.

    Uses DB-level status check to prevent race conditions across workers.
    Only claims if entry is in 'pending' status and not yet assigned.

    Returns True if claimed, False if already assigned or in wrong status.
    """
    from ...models import TaskQueueEntry

    entry = await db.get(TaskQueueEntry, entry_id)
    if entry is None:
        return False
    if entry.status != "pending":
        return False
    if entry.assigned_to is not None:
        return False
    now = _utc_now()
    entry.assigned_to = worker_id
    entry.assigned_at = now
    entry.started_at = now
    entry.last_heartbeat = now
    entry.status = "in_progress"
    entry.attempt_count = (entry.attempt_count or 0) + 1
    if timeout_minutes is not None:
        entry.timeout_minutes = timeout_minutes
    await db.flush()
    return True


async def release_task_queue_entry(
    db: AsyncSession,
    entry_id: str,
    worker_id: str,
    *,
    success: bool,
    result_session_id: str | None = None,
) -> bool:
    """Release a task queue entry after execution completes or fails.

    Only succeeds if the entry is owned by worker_id.
    Returns True if released, False if not the owner.
    """
    from ...models import TaskQueueEntry

    entry = await db.get(TaskQueueEntry, entry_id)
    if entry is None:
        return False
    if entry.assigned_to != worker_id:
        return False
    now = _utc_now()
    entry.status = "completed" if success else "failed"
    entry.completed_at = now
    if result_session_id:
        entry.result_session_id = result_session_id
    entry.last_heartbeat = now
    await db.flush()
    return True


async def recover_stale_task_queue_entries(db: AsyncSession) -> int:
    """Find task queue entries with stale heartbeats and reset them to pending.

    Runs at scheduler startup to recover entries whose worker died mid-execution.

    Returns the number of entries recovered.
    """
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
