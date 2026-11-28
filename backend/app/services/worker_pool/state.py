"""State and lifecycle helpers for worker pool operations."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import join, selectinload

from app.services.worker_pool.helpers import (
    _derive_expertise_level,
    _priority_label,
    _run_duration_minutes,
)

from ...models import (
    AgentWorker,
    Session,
    TaskQueueEntry,
    TaskRun,
    UsageEvent,
    WorkerCapacityLog,
    WorkerDomainExpertise,
    WorkerPoolConfig,
    WorkerRateLimit,
)
from ...time_utils import utc_now

# Bumped whenever this process changes a pool's queue settings, so a reader that caches them (the queue
# dispatcher, every 0.75 s) sees the change at once instead of after its cache expires.
_pool_config_generation = 0


def worker_pool_config_generation() -> int:
    return _pool_config_generation


def mark_worker_pool_config_changed() -> None:
    global _pool_config_generation
    _pool_config_generation += 1


async def get_or_create_worker_pool_config(db: AsyncSession, project_id: str) -> WorkerPoolConfig:
    row = (
        await db.execute(select(WorkerPoolConfig).where(WorkerPoolConfig.project_id == project_id))
    ).scalar_one_or_none()
    if row is None:
        row = WorkerPoolConfig(id=str(uuid.uuid4()), project_id=project_id)
        db.add(row)
        await db.flush()
    return row


async def get_or_create_worker_rate_limit(db: AsyncSession, project_id: str) -> WorkerRateLimit:
    row = (
        await db.execute(select(WorkerRateLimit).where(WorkerRateLimit.project_id == project_id))
    ).scalar_one_or_none()
    if row is None:
        row = WorkerRateLimit(id=str(uuid.uuid4()), project_id=project_id)
        db.add(row)
        await db.flush()
    return row


def _runtime_max_parallel_tasks(runtime) -> int:
    return max(1, int(runtime.max_parallel_tasks or 1))


def _runtime_active_tasks_count(runtime) -> int:
    return max(0, min(int(runtime.active_tasks_count or 0), _runtime_max_parallel_tasks(runtime)))


def _sync_runtime_slots(runtime) -> None:
    runtime.active_tasks_count = _runtime_active_tasks_count(runtime)
    runtime.available_slots = max(0, _runtime_max_parallel_tasks(runtime) - int(runtime.active_tasks_count or 0))


async def _refresh_rate_limit_usage(db: AsyncSession, row: WorkerRateLimit) -> None:
    now = utc_now()
    minute_start = now - timedelta(minutes=1)
    hour_start = now - timedelta(hours=1)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    usage_scope = join(UsageEvent, Session, UsageEvent.session_id == Session.id)

    rpm = (
        await db.execute(
            select(func.count(UsageEvent.id))
            .select_from(usage_scope)
            .where(
                Session.project_id == row.project_id,
                UsageEvent.created_at >= minute_start,
            )
        )
    ).scalar() or 0
    hour_usage = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0),
                func.coalesce(func.sum(UsageEvent.cost), 0),
            )
            .select_from(usage_scope)
            .where(
                Session.project_id == row.project_id,
                UsageEvent.created_at >= hour_start,
            )
        )
    ).one()
    day_cost = (
        await db.execute(
            select(func.coalesce(func.sum(UsageEvent.cost), 0))
            .select_from(usage_scope)
            .where(
                Session.project_id == row.project_id,
                UsageEvent.created_at >= day_start,
            )
        )
    ).scalar() or 0

    row.current_rpm = float(rpm or 0)
    row.current_hour_tokens = int(hour_usage[0] or 0)
    row.current_hour_cost = Decimal(str(hour_usage[1] or 0))
    row.current_day_cost = Decimal(str(day_cost or 0))
    row.reset_minute_at = now + timedelta(minutes=1)
    row.reset_hour_at = now + timedelta(hours=1)
    row.reset_day_at = (now + timedelta(days=1)).date()


async def claim_worker_assignment(
    db: AsyncSession,
    *,
    worker: AgentWorker,
    queue_entry: TaskQueueEntry,
    task_run: TaskRun,
) -> None:
    runtime = worker.runtime_state
    if runtime is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Worker runtime state missing")
    if queue_entry.assigned_to == worker.id and queue_entry.status == "in_progress":
        _sync_runtime_slots(runtime)
        return
    max_parallel_tasks = _runtime_max_parallel_tasks(runtime)
    active_tasks_count = _runtime_active_tasks_count(runtime)
    if active_tasks_count >= max_parallel_tasks:
        _sync_runtime_slots(runtime)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Worker has no available task slots")
    runtime.active_tasks_count = active_tasks_count + 1
    _sync_runtime_slots(runtime)
    runtime.current_priority = _priority_label(int(queue_entry.priority or 5))
    runtime.last_heartbeat = utc_now()

    queue_entry.assigned_to = worker.id
    queue_entry.assigned_at = utc_now()
    queue_entry.started_at = utc_now()
    queue_entry.last_heartbeat = utc_now()
    queue_entry.status = "in_progress"
    queue_entry.attempt_count = int(queue_entry.attempt_count or 0) + 1
    task_run.status = "running"
    task_run.started_at = task_run.started_at or utc_now()


async def release_worker_assignment(
    db: AsyncSession,
    *,
    worker_id: str | None,
    queue_entry: TaskQueueEntry | None,
    task_run: TaskRun,
    success: bool,
    required_domain: str,
) -> None:
    should_release_runtime = queue_entry is None or queue_entry.assigned_to == worker_id
    if worker_id:
        worker = (
            await db.execute(
                select(AgentWorker).options(selectinload(AgentWorker.runtime_state)).where(AgentWorker.id == worker_id)
            )
        ).scalar_one_or_none()
        if worker and worker.runtime_state and should_release_runtime:
            runtime = worker.runtime_state
            runtime.active_tasks_count = max(0, _runtime_active_tasks_count(runtime) - 1)
            _sync_runtime_slots(runtime)
            runtime.tasks_completed_today = int(runtime.tasks_completed_today or 0) + (1 if success else 0)
            if success and int(queue_entry.priority if queue_entry else 5) >= 8:
                runtime.incidents_resolved_today = int(runtime.incidents_resolved_today or 0) + 1
            runtime.current_priority = "idle" if runtime.active_tasks_count == 0 else runtime.current_priority
            runtime.last_heartbeat = utc_now()
            await record_capacity_snapshot(db, worker_id=worker.id)
            await update_worker_domain_expertise(
                db,
                worker_id=worker.id,
                domain=required_domain,
                success=success,
                duration_minutes=_run_duration_minutes(task_run),
            )

    if queue_entry:
        queue_entry.completed_at = task_run.completed_at or utc_now()
        queue_entry.status = "completed" if success else "failed"
        queue_entry.last_error = task_run.error
        queue_entry.result_session_id = task_run.session_id
        queue_entry.last_heartbeat = utc_now()
        queue_entry.assigned_to = None


async def record_capacity_snapshot(db: AsyncSession, *, worker_id: str) -> None:
    worker = (
        await db.execute(
            select(AgentWorker).options(selectinload(AgentWorker.runtime_state)).where(AgentWorker.id == worker_id)
        )
    ).scalar_one_or_none()
    if worker is None or worker.runtime_state is None:
        return
    queue_depth = (
        await db.execute(
            select(func.count(TaskQueueEntry.id)).where(
                TaskQueueEntry.project_id == worker.project_id,
                TaskQueueEntry.completed_at.is_(None),
                TaskQueueEntry.started_at.is_(None),
            )
        )
    ).scalar() or 0
    hour_start = utc_now() - timedelta(hours=1)
    usage_scope = join(UsageEvent, Session, UsageEvent.session_id == Session.id)
    hourly_cost = (
        await db.execute(
            select(func.coalesce(func.sum(UsageEvent.cost), 0))
            .select_from(usage_scope)
            .where(
                Session.project_id == worker.project_id,
                UsageEvent.created_at >= hour_start,
            )
        )
    ).scalar() or 0
    avg_duration = (
        await db.execute(
            select(func.avg(func.julianday(TaskRun.completed_at) - func.julianday(TaskRun.started_at))).where(
                TaskRun.task_id.is_not(None),
                TaskRun.completed_at.is_not(None),
                TaskRun.started_at.is_not(None),
            )
        )
    ).scalar()
    cpu_pressure = "low"
    if int(worker.runtime_state.active_tasks_count or 0) >= int(max(1, worker.runtime_state.max_parallel_tasks - 1)):
        cpu_pressure = "high"
    elif int(worker.runtime_state.active_tasks_count or 0) > 0:
        cpu_pressure = "medium"
    db.add(
        WorkerCapacityLog(
            id=str(uuid.uuid4()),
            worker_id=worker.id,
            queue_depth=int(queue_depth or 0),
            active_tasks=int(worker.runtime_state.active_tasks_count or 0),
            avg_task_duration_minutes=(float(avg_duration or 0) * 24 * 60) if avg_duration else None,
            llm_cost_last_hour=Decimal(str(hourly_cost or 0)),
            cpu_pressure=cpu_pressure,
        )
    )


async def update_worker_domain_expertise(
    db: AsyncSession,
    *,
    worker_id: str,
    domain: str,
    success: bool,
    duration_minutes: float | None,
) -> WorkerDomainExpertise | None:
    normalized_domain = str(domain or "any").strip().lower()
    if not normalized_domain or normalized_domain == "any":
        return None
    row = (
        await db.execute(
            select(WorkerDomainExpertise).where(
                WorkerDomainExpertise.worker_id == worker_id,
                WorkerDomainExpertise.domain == normalized_domain,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = WorkerDomainExpertise(
            id=str(uuid.uuid4()),
            worker_id=worker_id,
            domain=normalized_domain,
        )
        db.add(row)
        await db.flush()
    previous_tasks = int(row.tasks_completed or 0)
    previous_successes = round(float(row.success_rate or 0.5) * previous_tasks, 4)
    row.tasks_completed = previous_tasks + 1
    success_count = previous_successes + (1 if success else 0)
    row.success_rate = round(success_count / row.tasks_completed, 4)
    if duration_minutes is not None:
        if row.avg_resolution_time_minutes is None:
            row.avg_resolution_time_minutes = duration_minutes
        else:
            row.avg_resolution_time_minutes = round(
                ((float(row.avg_resolution_time_minutes) * previous_tasks) + duration_minutes) / row.tasks_completed,
                2,
            )
    row.expertise_level = _derive_expertise_level(int(row.tasks_completed or 0), float(row.success_rate or 0.5))
    return row
