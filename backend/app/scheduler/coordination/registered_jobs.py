"""The schedule jobs the scheduling owner registered, read from its acknowledgements."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SchedulerJobApplication
from .coordinator import STATUS_REGISTERED
from .fingerprint import apscheduler_job_id, parse_job_key
from .owner_lease import read_lease


async def registered_jobs_from_database(db: AsyncSession) -> list[dict[str, Any]]:
    lease = await read_lease(db)
    if lease is None or not lease.live:
        return []
    rows = (
        await db.execute(
            select(SchedulerJobApplication)
            .where(SchedulerJobApplication.owner_epoch == lease.epoch,
                   SchedulerJobApplication.status == STATUS_REGISTERED)
            .order_by(SchedulerJobApplication.job_key)
        )
    ).scalars()
    jobs: list[dict[str, Any]] = []
    for row in rows:
        kind, object_id = parse_job_key(row.job_key)
        jobs.append(
            {
                "id": apscheduler_job_id(kind, object_id),
                "next_run": str(row.next_run_at) if row.next_run_at else None,
                "trigger": None,
                "timezone": row.timezone,
                "registered_by": "scheduler_owner",
            }
        )
    return jobs


__all__ = ["registered_jobs_from_database"]
