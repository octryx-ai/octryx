"""Running task runs whose executing process is gone (also during a two-pod overlap)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import TaskRun
from ...time_utils import utc_now
from .process_lease import live_process_ids

STATUS_RUNNING = "running"
ERROR_OWNER_GONE = "Interrupted: the process executing this run stopped"


async def orphaned_running_task_runs(db: AsyncSession, *, include_unowned: bool) -> list[TaskRun]:
    query = select(TaskRun).where(TaskRun.status == STATUS_RUNNING)
    if not include_unowned:
        query = query.where(TaskRun.owner_process_id.isnot(None))
    runs = list((await db.execute(query)).scalars().all())
    live = await live_process_ids(db, (run.owner_process_id for run in runs))
    return [run for run in runs if run.owner_process_id is None or run.owner_process_id not in live]


async def settle_orphaned_task_runs(db: AsyncSession) -> list[TaskRun]:
    runs = await orphaned_running_task_runs(db, include_unowned=False)
    for run in runs:
        run.status = "error"
        run.error = ERROR_OWNER_GONE
        run.completed_at = utc_now()
    return runs


__all__ = ["ERROR_OWNER_GONE", "orphaned_running_task_runs", "settle_orphaned_task_runs"]
