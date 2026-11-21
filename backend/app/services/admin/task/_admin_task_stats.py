"""Task stats helpers shared by admin task flows.

Run chronology: an Action's summary ("last run") and its run history use one ordering,
``run_chronology_order``. A run's effective time is when it started, or, while it has not started,
when it was queued; no start time is invented. Runs with neither time sort after every timed run
(explicit NULLS LAST, so SQLite and PostgreSQL agree), and equal times fall back to the run id, so
the newest run is always the same row in both reads.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Task, TaskDependency, TaskQueueEntry, TaskRun, TaskStep
from ._admin_task_serialization import serialize_task


def run_chronology_order() -> tuple[Any, ...]:
    """ORDER BY clauses, newest first; the query must outer-join ``TaskQueueEntry`` on its run."""
    effective_time = func.coalesce(TaskRun.started_at, TaskQueueEntry.queued_at)
    return (effective_time.desc().nulls_last(), TaskRun.id.desc())


async def task_runs_for_task(db: AsyncSession, task_id: str) -> list[TaskRun]:
    runs_result = await db.execute(
        select(TaskRun)
        # A run has at most one queue entry (unique task_run_id), so the join adds no rows.
        .outerjoin(TaskQueueEntry, TaskQueueEntry.task_run_id == TaskRun.id)
        .where(TaskRun.task_id == task_id)
        .order_by(*run_chronology_order())
    )
    return runs_result.scalars().all()


async def task_step_count(db: AsyncSession, task_id: str) -> int:
    return (
        await db.execute(select(func.count()).select_from(TaskStep).where(TaskStep.task_id == task_id))
    ).scalar() or 0


async def task_dependency_count(db: AsyncSession, task_id: str) -> tuple[int, int]:
    dependency_count = (
        await db.execute(select(func.count()).select_from(TaskDependency).where(TaskDependency.task_id == task_id))
    ).scalar() or 0
    dependent_count = (
        await db.execute(
            select(func.count()).select_from(TaskDependency).where(TaskDependency.depends_on_task_id == task_id)
        )
    ).scalar() or 0
    return int(dependency_count), int(dependent_count)


async def serialize_task_with_stats(db: AsyncSession, task: Task) -> dict[str, Any]:
    runs = await task_runs_for_task(db, task.id)
    dependency_count, dependent_count = await task_dependency_count(db, task.id)
    queued_entries = (
        (
            await db.execute(
                select(TaskQueueEntry)
                .join(TaskRun, TaskRun.id == TaskQueueEntry.task_run_id)
                .where(
                    TaskRun.task_id == task.id,
                    TaskQueueEntry.started_at.is_(None),
                    TaskQueueEntry.completed_at.is_(None),
                )
                .order_by(TaskQueueEntry.priority.desc(), TaskQueueEntry.queued_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return serialize_task(
        task,
        run_count=len(runs),
        running_count=sum(1 for run in runs if run.status == "running"),
        queued_count=len(queued_entries),
        last_run=runs[0] if runs else None,
        step_count=await task_step_count(db, task.id),
        dependency_count=dependency_count,
        dependent_count=dependent_count,
        next_queue_priority=queued_entries[0].priority if queued_entries else None,
    )
