"""Task dependencies that block or allow a scheduled task."""

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import Project, Task, TaskDependency, TaskRun
from app.scheduler import TaskScheduler


@pytest.mark.asyncio
async def test_scheduler_skips_task_when_dependency_is_unmet(db, auth_user):
    import app.db as database_module

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    task_a = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Upstream task",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=auth_user.id,
        is_active=True,
    )
    task_b = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Dependent task",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=auth_user.id,
        is_active=True,
    )
    db.add_all([task_a, task_b])
    await db.flush()
    db.add(TaskDependency(task_id=task_b.id, depends_on_task_id=task_a.id, condition="success"))
    await db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    await scheduler._execute_task(task_b.id, trigger_type="manual")
    monkeypatch.undo()

    latest_run = (
        await db.execute(
            select(TaskRun).where(TaskRun.task_id == task_b.id).order_by(TaskRun.started_at.desc()).limit(1)
        )
    ).scalar_one()
    assert latest_run.status == "skipped"
    assert latest_run.output["status"] == "blocked_by_dependencies"
    assert latest_run.output["unmet_dependencies"][0]["depends_on_task_id"] == task_a.id


@pytest.mark.asyncio
async def test_scheduler_allows_task_when_dependency_condition_matches(db, monkeypatch, auth_user):
    import app.db as database_module

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    task_a = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Upstream success task",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=auth_user.id,
        is_active=True,
    )
    task_b = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Dependent task",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=auth_user.id,
        is_active=True,
        config={"prompt": "Hello"},
    )
    db.add_all([task_a, task_b])
    await db.flush()
    db.add(TaskDependency(task_id=task_b.id, depends_on_task_id=task_a.id, condition="success"))
    db.add(
        TaskRun(
            id=str(uuid.uuid4()),
            task_id=task_a.id,
            session_id=None,
            status="success",
            started_by=auth_user.id,
            input_={},
            output={"status": "completed"},
        )
    )
    await db.commit()

    async def fake_run_agent_for_task(db, task, prompt, **kwargs):
        class DummySession:
            id = "session-123"

        return DummySession(), {"response": "done"}

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)
    await scheduler._execute_task(task_b.id, trigger_type="manual")

    latest_run = (
        await db.execute(
            select(TaskRun).where(TaskRun.task_id == task_b.id).order_by(TaskRun.started_at.desc()).limit(1)
        )
    ).scalar_one()
    assert latest_run.status == "success"
