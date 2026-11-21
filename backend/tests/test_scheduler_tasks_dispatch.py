"""Scheduler startup recovery of stale runs, priority dispatch and pruning stale task locks."""

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import AgentWorker, Project, Session, Task, TaskRun, User, WorkerOnboarding, WorkerRuntimeState
from app.scheduler import TaskScheduler
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_scheduler_startup_marks_shared_stale_runs_without_double_finalizing_session(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="History Watch",
        description="",
        task_type="agent_run",
        agent_type="change",
        owner_id=admin.id,
        is_active=True,
        config={"prompt": "Process the item."},
    )
    db.add(task)
    await db.flush()

    first_run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        session_id=None,
        trigger_type="schedule",
        status="running",
        started_by=admin.id,
        input_={},
        started_at=utc_now(),
    )
    second_run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        session_id=None,
        trigger_type="schedule",
        status="running",
        started_by=admin.id,
        input_={},
        started_at=utc_now(),
    )
    db.add_all([first_run, second_run])
    await db.flush()

    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={
            "task_id": task.id,
            "task_name": task.name,
            "task_run_id": second_run.id,
            "ticket_id": "RIVER-1",
            "trigger": "schedule",
        },
    )
    db.add(session)
    await db.flush()

    first_run.session_id = session.id
    second_run.session_id = session.id
    await db.commit()

    scheduler = TaskScheduler()
    finalized = []
    original_finalize = scheduler._finalize_task_session_tree

    async def spy_finalize(db_obj, root_session_id, *, status, stop_reason=None):
        finalized.append((root_session_id, status, stop_reason))
        return await original_finalize(db_obj, root_session_id, status=status, stop_reason=stop_reason)

    monkeypatch.setattr(scheduler, "_finalize_task_session_tree", spy_finalize)

    await scheduler._mark_stale_running_runs(db)

    await db.refresh(first_run)
    await db.refresh(second_run)
    await db.refresh(session)

    assert first_run.status == "error"
    assert second_run.status == "error"
    assert first_run.error == "Marked stale after scheduler startup"
    assert second_run.error == "Marked stale after scheduler startup"
    assert finalized == [(session.id, "error", "task_failed")]
    assert session.status == "error"
    assert session.metadata_["task_run_id"] == second_run.id


@pytest.mark.asyncio
async def test_scheduler_dispatches_higher_priority_task_first(db, monkeypatch):
    import app.db as database_module

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Queue sorter",
        role="ops",
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
        current_priority="idle",
        active_tasks_count=0,
        max_parallel_tasks=2,
        available_slots=2,
    )
    low = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Low priority",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"queue_priority": 2},
    )
    high = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="High priority",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"queue_priority": 9},
    )
    db.add_all([worker, low, high])
    await db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    scheduler._max_parallel_queue_tasks = 2
    order: list[str] = []

    async def fake_execute_task(
        task_id: str,
        trigger_type: str = "manual",
        trigger_id: str | None = None,
        task_run_id: str | None = None,
        assigned_worker_id: str | None = None,
        queue_domain: str | None = None,
    ):
        order.append(task_id)

    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_execute_task", fake_execute_task)

    await scheduler.run_task_now(low.id, started_by=admin.id)
    await scheduler.run_task_now(high.id, started_by=admin.id)
    dispatched = await scheduler._dispatch_queued_runs_once()
    await asyncio.sleep(0)

    assert dispatched == 2
    assert order == [high.id, low.id]


@pytest.mark.asyncio
async def test_scheduler_prunes_stale_active_task_locks_before_dispatch(db, monkeypatch):
    import app.db as database_module

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Stale lock worker",
        role="ops",
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
        current_priority="idle",
        active_tasks_count=0,
        max_parallel_tasks=1,
        available_slots=1,
    )
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Dispatch after stale lock",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"queue_priority": 9, "required_domain": "kubernetes"},
    )
    db.add_all([worker, task])
    await db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    scheduler._max_parallel_queue_tasks = 1
    scheduler._active_task_ids.add(task.id)
    scheduler._running_futures[task.id] = asyncio.create_task(asyncio.sleep(0))
    await asyncio.sleep(0)
    order: list[str] = []

    async def fake_execute_task(
        task_id: str,
        trigger_type: str = "manual",
        trigger_id: str | None = None,
        task_run_id: str | None = None,
        assigned_worker_id: str | None = None,
        queue_domain: str | None = None,
    ):
        order.append(task_id)

    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_execute_task", fake_execute_task)

    await scheduler.run_task_now(task.id, started_by=admin.id)
    dispatched = await scheduler._dispatch_queued_runs_once()
    await asyncio.sleep(0)

    assert dispatched == 1
    assert order == [task.id]
