"""Adding and running tasks now, failure retry decisions and outbound webhook enqueue failures."""

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import FailedTaskRun, Project, Task, TaskQueueEntry, TaskRun
from app.scheduler import TaskScheduler


def test_scheduler_add_task_uses_schedule_trigger_type(monkeypatch):
    scheduler = TaskScheduler()
    observed = {}

    def fake_add_job(func, trigger, id, args, replace_existing, max_instances):
        observed["func"] = func
        observed["trigger"] = trigger
        observed["id"] = id
        observed["args"] = args
        observed["replace_existing"] = replace_existing
        observed["max_instances"] = max_instances

    monkeypatch.setattr(scheduler.scheduler, "add_job", fake_add_job)

    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        name="Scheduled watch",
        description="",
        task_type="agent_run",
        agent_type="change",
        schedule="*/15 * * * *",
        owner_id=str(uuid.uuid4()),
        is_active=True,
    )

    from app.scheduler.coordination.fingerprint import ScheduleRecord, task_fingerprint

    scheduler._register_job(ScheduleRecord("task", task.id, task.schedule, task.id, task.name, task_fingerprint(task)))

    assert observed["id"] == f"task_{task.id}"
    assert observed["args"] == [task.id, "schedule"]
    assert (observed["replace_existing"], observed["max_instances"]) == (True, 1)


@pytest.mark.asyncio
async def test_scheduler_run_task_now_enqueues_task_run_with_priority(db, monkeypatch, auth_user):
    import app.db as database_module

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Queued task",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=auth_user.id,
        is_active=True,
        config={"queue_priority": 9},
    )
    db.add(task)
    await db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)

    payload = await scheduler.run_task_now(task.id, started_by=auth_user.id)

    task_run = (await db.execute(select(TaskRun).where(TaskRun.id == payload["task_run_id"]))).scalar_one()
    queue_entry = (
        await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == task_run.id))
    ).scalar_one()
    assert payload["status"] == "queued"
    assert task_run.status == "queued"
    assert task_run.started_at is None
    assert queue_entry.priority == 9
    assert payload["priority"] == 9
    assert payload["estimated_wait_seconds"] >= 0


@pytest.mark.asyncio
async def test_scheduler_task_failure_records_retry_decision_and_queue_state(db, monkeypatch, auth_user):
    import app.db as database_module

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Queued failure task",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=auth_user.id,
        is_active=True,
        config={"prompt": "fail predictably"},
    )
    db.add(task)
    await db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    async def fake_run_agent_for_task(db, task, prompt, **kwargs):
        raise RuntimeError("worker failed with sk-test-secret")

    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)

    payload = await scheduler.run_task_now(task.id, started_by=auth_user.id)
    await scheduler._execute_task(task.id, task_run_id=payload["task_run_id"], trigger_type="manual")

    task_run = (await db.execute(select(TaskRun).where(TaskRun.id == payload["task_run_id"]))).scalar_one()
    queue_entry = (
        await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == task_run.id))
    ).scalar_one()
    failed_run = (await db.execute(select(FailedTaskRun).where(FailedTaskRun.task_run_id == task_run.id))).scalar_one()
    failure_decision = task_run.output["failure_decision"]

    assert task_run.status == "error"
    assert queue_entry.status == "retry_pending"
    assert queue_entry.next_retry_at == failed_run.next_retry_at
    assert queue_entry.last_error == "scheduled_task_failed error_type=RuntimeError"
    assert task_run.error == "scheduled_task_failed error_type=RuntimeError"
    assert "worker failed" not in str(task_run.output)
    assert failure_decision["status"] == "pending_retry"
    assert failure_decision["retryable"] is True
    assert failure_decision["terminal"] is False
    assert failure_decision["retry_delay_seconds"] == 0
    assert failure_decision["queue_status"] == "retry_pending"
    assert failure_decision["reason"] == "retry_scheduled"
    assert scheduler.scheduler.get_job(f"failed-task-retry:{failed_run.id}") is not None


@pytest.mark.asyncio
async def test_scheduler_records_outbound_webhook_enqueue_failure_on_task_run(db, monkeypatch, auth_user):
    import app.db as database_module
    import app.scheduler.execution.task_run_finish as task_run_finish

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Webhook enqueue failure task",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=auth_user.id,
        is_active=True,
        config={"prompt": "fail predictably"},
    )
    db.add(task)
    await db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    async def fake_run_agent_for_task(db, task, prompt, **kwargs):
        raise RuntimeError("worker blew up")

    async def exploding_emit(*args, **kwargs):
        raise RuntimeError("outbound webhook queue is down")

    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)
    monkeypatch.setattr(task_run_finish, "emit_outbound_webhook_event", exploding_emit)

    payload = await scheduler.run_task_now(task.id, started_by=auth_user.id)
    await scheduler._execute_task(task.id, task_run_id=payload["task_run_id"], trigger_type="manual")

    task_run = (await db.execute(select(TaskRun).where(TaskRun.id == payload["task_run_id"]))).scalar_one()

    assert task_run.status == "error"
    assert task_run.completed_at is not None

    webhook_trail = task_run.output["webhook_enqueue"]
    assert webhook_trail["status"] == "failed"
    assert webhook_trail["event_type"] == "task.failed"
    assert "outbound webhook queue is down" in webhook_trail["error"]
    assert webhook_trail["failed_at"]

    assert task_run.output["failure_decision"]["retryable"] is True
