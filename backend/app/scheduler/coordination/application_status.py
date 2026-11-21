"""Read model: has the scheduling worker applied this Scheduler row?

``worker_application`` describes *registration*, not task execution:

* ``paused`` — the row is inactive: its schedule enqueues no new run (enforced at fire time); runs
  already queued or running are not affected.
* ``worker_unavailable`` — no live owner lease: no scheduling worker currently registers schedules.
* ``pending`` — an owner is live, but its acknowledgement is missing, from another epoch, for other
  content, or carries a next run older than the refresh window (the owner stopped refreshing).
* ``invalid_schedule`` — the current owner applied this exact content and found it unschedulable.
* ``applied`` — the current owner acknowledged exactly this content with status ``registered``,
  which it writes only for a job APScheduler holds; ``next_run_at`` is that job's next run (UTC ISO,
  or ``null`` when the trigger has no further run) in ``timezone``. Any other or unknown stored
  status reads ``pending``.

Batched: one lease read, one acknowledgement read and one clock read for any number of rows.
No process id, epoch, token, secret or error text leaves this module.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SchedulerJobApplication
from .clock import db_now
from .coordinator import DEFAULT_RECONCILE_SECONDS, STATUS_INVALID, STATUS_REGISTERED
from .fingerprint import SCHEDULER_KIND, job_key, scheduler_fingerprint
from .owner_lease import read_lease

STATUS_PAUSED = "paused"
STATUS_PENDING = "pending"
STATUS_APPLIED = "applied"
STATUS_WORKER_UNAVAILABLE = "worker_unavailable"
STATUS_INVALID_SCHEDULE = STATUS_INVALID
# The owner refreshes next runs every reconcile and after every fire; twice that plus APScheduler's
# default misfire grace and a margin is the oldest next run still treated as current.
NEXT_RUN_FRESHNESS = timedelta(seconds=2 * DEFAULT_RECONCILE_SECONDS + 1 + 5)


def _status(status: str, next_run_at: datetime | None = None, timezone: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "next_run_at": f"{next_run_at.isoformat()}Z" if next_run_at is not None else None,
        "timezone": timezone,
    }


async def scheduler_worker_applications(db: AsyncSession, schedulers: list[Any]) -> dict[str, dict[str, Any]]:
    """``worker_application`` per Scheduler id for the given rows."""
    if not schedulers:
        return {}
    lease = await read_lease(db)
    keys = [job_key(SCHEDULER_KIND, scheduler.id) for scheduler in schedulers]
    acknowledgements = {
        row.job_key: row
        for row in (
            await db.execute(select(SchedulerJobApplication).where(SchedulerJobApplication.job_key.in_(keys)))
        ).scalars()
    }
    oldest_current = (await db_now(db)) - NEXT_RUN_FRESHNESS
    result: dict[str, dict[str, Any]] = {}
    for scheduler in schedulers:
        if scheduler.is_active is not True:
            result[scheduler.id] = _status(STATUS_PAUSED)
            continue
        if lease is None or not lease.live:
            result[scheduler.id] = _status(STATUS_WORKER_UNAVAILABLE)
            continue
        ack = acknowledgements.get(job_key(SCHEDULER_KIND, scheduler.id))
        current_content = scheduler_fingerprint(scheduler)
        if ack is None or int(ack.owner_epoch) != lease.epoch or ack.applied_fingerprint != current_content:
            result[scheduler.id] = _status(STATUS_PENDING)
        elif ack.status == STATUS_INVALID:
            result[scheduler.id] = _status(STATUS_INVALID_SCHEDULE, timezone=ack.timezone)
        elif ack.status != STATUS_REGISTERED:
            result[scheduler.id] = _status(STATUS_PENDING)
        elif ack.next_run_at is not None and ack.next_run_at < oldest_current:
            result[scheduler.id] = _status(STATUS_PENDING)
        else:
            result[scheduler.id] = _status(STATUS_APPLIED, ack.next_run_at, ack.timezone)
    return result
