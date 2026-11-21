"""Claiming a worker assignment blocks without free slots, and releasing it is idempotent and never makes slots negative."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Project, TaskRun, User
from app.services.worker_pool.state import claim_worker_assignment, release_worker_assignment
from app.time_utils import utc_now
from tests.worker_pool_service_support import _queued_task, _ready_worker


@pytest.mark.asyncio
async def test_claim_worker_assignment_blocks_when_worker_has_no_slots(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = _ready_worker(project, name="Full Worker")
    worker.runtime_state.active_tasks_count = 1
    worker.runtime_state.max_parallel_tasks = 1
    worker.runtime_state.available_slots = 0
    db.add(worker)
    task, queue_entry = await _queued_task(
        db,
        project=project,
        owner=admin,
        config={"required_domain": "kubernetes"},
        required_domain="kubernetes",
        priority=8,
    )
    task_run = (await db.execute(select(TaskRun).where(TaskRun.task_id == task.id))).scalar_one()

    with pytest.raises(HTTPException) as exc_info:
        await claim_worker_assignment(db, worker=worker, queue_entry=queue_entry, task_run=task_run)

    assert exc_info.value.status_code == 409
    assert worker.runtime_state.active_tasks_count == 1
    assert worker.runtime_state.available_slots == 0
    assert queue_entry.assigned_to is None
    assert queue_entry.status == "pending"


@pytest.mark.asyncio
async def test_release_worker_assignment_is_idempotent_and_restores_slots(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = _ready_worker(project, name="Release Worker")
    worker.runtime_state.active_tasks_count = 1
    worker.runtime_state.max_parallel_tasks = 2
    worker.runtime_state.available_slots = 1
    db.add(worker)
    task, queue_entry = await _queued_task(
        db,
        project=project,
        owner=admin,
        config={"required_domain": "kubernetes"},
        required_domain="kubernetes",
        priority=9,
    )
    task_run = (await db.execute(select(TaskRun).where(TaskRun.task_id == task.id))).scalar_one()
    queue_entry.assigned_to = worker.id
    queue_entry.status = "in_progress"
    task_run.status = "success"
    task_run.completed_at = utc_now()
    await db.commit()

    await release_worker_assignment(
        db,
        worker_id=worker.id,
        queue_entry=queue_entry,
        task_run=task_run,
        success=True,
        required_domain="kubernetes",
    )
    await release_worker_assignment(
        db,
        worker_id=worker.id,
        queue_entry=queue_entry,
        task_run=task_run,
        success=True,
        required_domain="kubernetes",
    )

    assert worker.runtime_state.active_tasks_count == 0
    assert worker.runtime_state.available_slots == 2
    assert worker.runtime_state.tasks_completed_today == 1
    assert worker.runtime_state.incidents_resolved_today == 1
    assert queue_entry.assigned_to is None
    assert queue_entry.status == "completed"


@pytest.mark.asyncio
async def test_release_worker_assignment_failure_never_makes_slots_negative(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = _ready_worker(project, name="Failure Release Worker")
    worker.runtime_state.active_tasks_count = 0
    worker.runtime_state.max_parallel_tasks = 2
    worker.runtime_state.available_slots = 2
    db.add(worker)
    task, queue_entry = await _queued_task(
        db,
        project=project,
        owner=admin,
        config={"required_domain": "kubernetes"},
        required_domain="kubernetes",
        priority=7,
    )
    task_run = (await db.execute(select(TaskRun).where(TaskRun.task_id == task.id))).scalar_one()
    queue_entry.assigned_to = worker.id
    queue_entry.status = "in_progress"
    task_run.status = "error"
    task_run.error = "failed"
    task_run.completed_at = utc_now()
    await db.commit()

    await release_worker_assignment(
        db,
        worker_id=worker.id,
        queue_entry=queue_entry,
        task_run=task_run,
        success=False,
        required_domain="kubernetes",
    )

    assert worker.runtime_state.active_tasks_count == 0
    assert worker.runtime_state.available_slots == 2
    assert worker.runtime_state.tasks_completed_today == 0
    assert queue_entry.assigned_to is None
    assert queue_entry.status == "failed"
    assert queue_entry.last_error == "failed"
