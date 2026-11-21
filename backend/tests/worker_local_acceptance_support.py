"""Seeding and lookup helpers for the local worker acceptance tests."""

import uuid
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.orm import selectinload

import app.db as database_module
from app.models import (
    AgentWorker,
    Task,
    TaskQueueEntry,
    TaskRun,
    WorkerOnboarding,
    WorkerRuntimeState,
)
from app.scheduler import TaskScheduler
from app.time_utils import utc_now


def acceptance_worker_payload(project_id, admin_id):
    return {
        "project_id": project_id,
        "name": "Acceptance Worker",
        "role": "Senior SRE",
        "description": "Local acceptance worker",
        "autonomy_level": "supervised",
        "allowed_actions": ["diagnose"],
        "forbidden_actions": ["delete_production_data"],
        "report_channel": "slack:#acceptance",
        "escalation_user_id": admin_id,
        "warmup_period_hours": 0,
        "max_parallel_tasks": 2,
    }


async def mark_onboarding_ready(db, worker_id):
    onboarding = (
        await db.execute(select(WorkerOnboarding).where(WorkerOnboarding.worker_id == worker_id))
    ).scalar_one()
    onboarding.onboarding_status = "ready"
    onboarding.ready_at = utc_now()


async def seed_queued_diagnosis_task(db, project, admin):
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Acceptance queued diagnosis",
        description="Exercise DB queue dispatch and worker assignment.",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"queue_priority": 9, "required_domain": "kubernetes"},
    )
    db.add(task)
    await db.commit()
    return task


def stub_queue_scheduler(monkeypatch, db):
    """A one-slot scheduler on the test session that records dispatches instead of running tasks."""

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    scheduler._max_parallel_queue_tasks = 1
    dispatched_calls: list[tuple[str | None, str | None]] = []

    async def fake_execute_task(
        task_id: str,
        trigger_type: str = "manual",
        trigger_id: str | None = None,
        task_run_id: str | None = None,
        assigned_worker_id: str | None = None,
        queue_domain: str | None = None,
    ):
        dispatched_calls.append((assigned_worker_id, queue_domain))

    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_execute_task", fake_execute_task)
    return scheduler, dispatched_calls


async def load_worker_with_runtime(db, worker_id):
    return (
        await db.execute(
            select(AgentWorker).options(selectinload(AgentWorker.runtime_state)).where(AgentWorker.id == worker_id)
        )
    ).scalar_one()


def _full_worker(project):
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Full Acceptance Worker",
        role="SRE",
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id,
        onboarding_status="ready",
        ready_at=utc_now(),
        warmup_period_hours=0,
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id,
        status="active",
        current_priority="high",
        active_tasks_count=1,
        max_parallel_tasks=1,
        available_slots=0,
    )
    return worker


async def seed_full_worker_with_pending_entry(db, project, admin):
    """A worker with no free slot plus a pending queued run it should not be able to claim."""
    worker = _full_worker(project)
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Capacity denied task",
        description="Proves full workers reject new local assignments.",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"queue_priority": 8, "required_domain": "kubernetes"},
    )
    task_run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        trigger_type="manual",
        status="queued",
        started_by=admin.id,
        input_={},
    )
    queue_entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=task_run.id,
        project_id=project.id,
        task_type="scheduled_task",
        status="pending",
        priority=8,
        required_domain="kubernetes",
        queue_backend="database",
    )
    db.add_all([worker, task, task_run, queue_entry])
    await db.commit()
    return worker, task_run, queue_entry
