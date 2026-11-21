"""The scheduler enqueues runs with worker pool metadata and dispatches connector-only and platform tasks without a worker."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.db as database_module
from app.models import (
    AgentWorker,
    Project,
    Task,
    TaskQueueEntry,
    TaskRun,
    TaskStep,
    User,
    WorkerOnboarding,
    WorkerRuntimeState,
)
from app.scheduler import TaskScheduler
from app.scheduler.execution._step_connector_execution import (
    CONNECTOR_STEP_WORKSPACE_ROOT_ENV,
    execute_connector_action,
)
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_scheduler_enqueued_runs_include_worker_pool_metadata_and_assignment(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Queue Alex",
        role="SRE",
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id, onboarding_status="ready", ready_at=utc_now(), warmup_period_hours=0
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id,
        status="active",
        current_priority="idle",
        active_tasks_count=0,
        max_parallel_tasks=2,
        available_slots=2,
    )
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Restart stuck pod",
        description="Run kubectl checks",
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
    seen: list[tuple[str | None, str | None]] = []

    async def fake_execute_task(
        task_id: str,
        trigger_type: str = "manual",
        trigger_id: str | None = None,
        task_run_id: str | None = None,
        assigned_worker_id: str | None = None,
        queue_domain: str | None = None,
    ):
        seen.append((assigned_worker_id, queue_domain))

    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_execute_task", fake_execute_task)

    payload = await scheduler.run_task_now(task.id, started_by=admin.id)
    queue_entry = (
        await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == payload["task_run_id"]))
    ).scalar_one()
    assert queue_entry.project_id == project.id
    assert queue_entry.required_domain == "kubernetes"
    assert queue_entry.status == "pending"
    assert queue_entry.queue_backend == "database"

    dispatched = await scheduler._dispatch_queued_runs_once()
    assert dispatched == 1
    await asyncio.sleep(0)

    await db.refresh(queue_entry)
    await db.refresh(worker.runtime_state)
    assert seen == [(worker.id, "kubernetes")]
    assert queue_entry.assigned_to == worker.id
    assert queue_entry.status == "in_progress"
    assert worker.runtime_state.active_tasks_count == 1


@pytest.mark.asyncio
async def test_scheduler_dispatches_connector_only_action_without_worker(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Connector-only action",
        description="Runs deterministic platform action",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"queue_priority": 5},
    )
    step = TaskStep(
        id=str(uuid.uuid4()),
        task_id=task.id,
        position=1,
        name="Normalize",
        step_type="output",
        connector="knowledge",
        connector_action="normalize_bronze_knowledge",
        connector_params_json="{}",
        is_enabled=True,
    )
    db.add_all([task, step])
    await db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    scheduler._max_parallel_queue_tasks = 1
    seen: list[tuple[str | None, str | None]] = []

    async def fake_execute_task(
        task_id: str,
        trigger_type: str = "manual",
        trigger_id: str | None = None,
        task_run_id: str | None = None,
        assigned_worker_id: str | None = None,
        queue_domain: str | None = None,
    ):
        seen.append((assigned_worker_id, queue_domain))

    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_execute_task", fake_execute_task)

    payload = await scheduler.run_task_now(task.id, started_by=admin.id)
    queue_entry = (
        await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == payload["task_run_id"]))
    ).scalar_one()

    dispatched = await scheduler._dispatch_queued_runs_once()
    assert dispatched == 1
    await asyncio.sleep(0)

    await db.refresh(queue_entry)
    assert seen == [(None, "any")]
    assert queue_entry.status == "in_progress"
    assert queue_entry.assigned_to is None
    assert queue_entry.last_error is None


@pytest.mark.asyncio
async def test_scheduler_dispatches_deterministic_platform_task_without_worker(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Scheduled platform sync",
        description="Runs deterministic platform sync without agent worker capacity.",
        task_type="secure_work_jira_sync",
        agent_type="operations",
        owner_id=admin.id,
        is_active=True,
        config={
            "queue_priority": 5,
            "required_domain": "jira",
            "local_execution": "deterministic",
            "requires_worker": False,
            "sync_config_id": "sync-config-1",
            "limit": 1000,
        },
    )
    db.add(task)
    await db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    scheduler._max_parallel_queue_tasks = 1
    seen: list[tuple[str | None, str | None]] = []

    async def fake_execute_task(
        task_id: str,
        trigger_type: str = "manual",
        trigger_id: str | None = None,
        task_run_id: str | None = None,
        assigned_worker_id: str | None = None,
        queue_domain: str | None = None,
    ):
        seen.append((assigned_worker_id, queue_domain))

    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_execute_task", fake_execute_task)

    payload = await scheduler.run_task_now(task.id, started_by=admin.id)
    queue_entry = (
        await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == payload["task_run_id"]))
    ).scalar_one()
    assert queue_entry.status == "pending"

    dispatched = await scheduler._dispatch_queued_runs_once()
    assert dispatched == 1
    await asyncio.sleep(0)

    await db.refresh(queue_entry)
    assert seen == [(None, "jira")]
    assert queue_entry.status == "in_progress"
    assert queue_entry.assigned_to is None
    assert queue_entry.last_error is None


@pytest.mark.asyncio
async def test_connector_action_uses_configured_writable_workspace_root(db, monkeypatch, tmp_path):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    workspace_root = tmp_path / "action-workspace"
    monkeypatch.setenv(CONNECTOR_STEP_WORKSPACE_ROOT_ENV, str(workspace_root))
    captured: dict[str, str] = {}

    async def fake_execute_tool(tool_name, params, context):
        captured["tool_name"] = tool_name
        captured["workspace_root"] = context.workspace_root
        captured["project_id"] = context.project_ids[0]
        return {"status": "ok", "params": params}

    monkeypatch.setattr("app.tools.registry.execute_tool", fake_execute_tool)

    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Connector workspace action",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={},
    )
    task_run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        status="running",
        started_by=admin.id,
    )
    step = SimpleNamespace(
        connector_action="sync_bitbucket_repository_bronze",
        connector_params={"project_id": project.id},
    )
    db.add_all([task, task_run])
    await db.flush()

    result = await execute_connector_action(
        step=step,
        context={},
        db=db,
        task=task,
        task_run=task_run,
        render_template_params=lambda params, _context: params,
    )

    assert result["status"] == "ok"
    assert captured == {
        "tool_name": "sync_bitbucket_repository_bronze",
        "workspace_root": str(workspace_root.resolve()),
        "project_id": project.id,
    }
    assert workspace_root.exists()
