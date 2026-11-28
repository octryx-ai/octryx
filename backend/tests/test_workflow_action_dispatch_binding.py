"""An explicitly authored workflow Action can use ordinary local scheduler dispatch."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import FlowDefinition, Task, TaskStep, User
from app.scheduler import TaskScheduler
from app.scheduler.dispatch.loop import _can_execute_locally_without_worker
from app.services.admin.task import _admin_task_management as admin_tasks
from tests.action_agent_binding_support import _dispatch, _entry, _scheduler
from tests.scheduler.test_action_runtime_admission import _admin, _project, _run
from tests.scripted_pool_support import (
    scripted_pool,  # noqa: F401 - fixture
    scripted_turns,  # noqa: F401 - fixture
)


def _config(**changes):
    return {"prompt": "Analyse this alert using permitted evidence only.",
            "workflow_run": {"workflow_key": "incident-analysis", "runtime_target": {"kind": "server"}}, **changes}


async def _bound(db, *, binding="workflow_run"):
    project = await _project(db, "workflow-binding")
    owner = await _admin(db)
    data = {"name": "Incident Action", "task_type": "agent_run", "agent_type": "diagnosis",
            "project_id": project.id, "config": _config(), "dispatch_binding": binding}
    saved = await admin_tasks.create_task(db, user_id=owner.id, payload=data)
    return await db.get(Task, saved["id"]), data


async def test_binding_is_explicit_never_inferred_and_updates_keep_it(db):
    task, data = await _bound(db)
    assert task.dispatch_binding == "workflow_run"
    owner = await _admin(db)
    data.pop("dispatch_binding")
    with pytest.raises(HTTPException) as missing:
        await admin_tasks.create_task(db, user_id=owner.id, payload=data)
    assert missing.value.detail["code"] == "dispatch_binding_invalid"
    own = await admin_tasks.create_task(db, user_id=owner.id, payload={**data, "dispatch_binding": "task_definition"})
    assert own["dispatch_binding"] == "task_definition"
    assert await _can_execute_locally_without_worker(db, await db.get(Task, own["id"]))  # an agent turn: runners
    assert (await admin_tasks.update_task(db, task_id=task.id, payload={"name": "renamed"}))["dispatch_binding"] == "workflow_run"
    with pytest.raises(HTTPException):
        await admin_tasks.update_task(db, task_id=task.id, payload={"dispatch_binding": None})


@pytest.mark.parametrize("change,code", [
    ({"task_type": "custom"}, "dispatch_binding_type_unsupported"),
    ({"config": {"prompt": "x"}}, "dispatch_binding_workflow_required"),
    ({"config": _config(workflow_run={"workflow_key": ""})}, "dispatch_binding_workflow_required"),
    ({"config": _config(workflow_run={"workflow_key": "unknown", "runtime_target": {"kind": "server"}})}, "dispatch_binding_workflow_unavailable"),
    ({"config": _config(workflow_run={"workflow_key": "incident-analysis"})}, "dispatch_binding_server_required"),
    ({"config": _config(workflow_run={"workflow_key": "incident-analysis", "runtime_target": {"kind": "device"}})}, "dispatch_binding_server_required"),
    ({"config": _config(prompt=" ")}, "action_instruction_missing"),
])
async def test_invalid_create_is_refused_without_task_write(db, change, code):
    task, data = await _bound(db)
    before = (await db.execute(select(func.count()).select_from(Task))).scalar_one()
    with pytest.raises(HTTPException) as exc:
        await admin_tasks.create_task(db, user_id=task.owner_id, payload={**data, **change})
    assert exc.value.status_code == 422 and exc.value.detail["code"] == code
    assert (await db.execute(select(func.count()).select_from(Task))).scalar_one() == before


@pytest.mark.parametrize("mutation,code", [
    ("unpublished", "dispatch_binding_workflow_unavailable"),
    ("foreign", "dispatch_binding_workflow_unavailable"),
    ("steps", "dispatch_binding_steps_enabled"),
    ("agent", "dispatch_binding_agent_forbidden"),
    ("inactive_owner", "dispatch_binding_owner_unavailable"),
    ("inactive_workspace", "dispatch_binding_owner_unavailable"),
    ("device", "dispatch_binding_server_required"),
])
async def test_later_state_change_is_refused_before_session_or_model(db, monkeypatch, mutation, code):
    task, _data = await _bound(db)
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == "incident-analysis"))).scalar_one()
    if mutation == "unpublished":
        flow.status = "draft"
    elif mutation == "foreign":
        flow.project_id = (await _project(db, "foreign-flow")).id
    elif mutation == "steps":
        db.add(TaskStep(task_id=task.id, name="unexpected", is_enabled=True))
    elif mutation == "agent":
        task.config = _config(agent_definition_id="unexpected")
    elif mutation == "inactive_owner":
        (await db.get(User, task.owner_id)).is_active = False
    elif mutation == "inactive_workspace":
        from app.models import Project
        (await db.get(Project, task.project_id)).is_active = False
    else:
        task.config = _config(workflow_run={"workflow_key": "incident-analysis", "runtime_target": {"kind": "device"}})
    await db.commit()
    run, queue, calls = await _run(db, monkeypatch, task)
    assert calls == [] and run.session_id is None
    assert run.error == code and run.status == "error"
    assert queue.completed_at is not None


async def test_ordinary_queue_claims_workflow_and_keeps_implicit_waiting(db, monkeypatch):
    bound, _ = await _bound(db)
    implicit, _ = await _bound(db, binding="task_definition")
    from app.models.project.task import TaskStep

    db.add(TaskStep(task_id=implicit.id, position=1, name="Fix", step_type="agent", is_enabled=True))  # needs a worker
    await db.commit()
    scheduler, started = _scheduler(db, monkeypatch)
    yes = await scheduler.run_task_now(bound.id, started_by=bound.owner_id)
    no = await scheduler.run_task_now(implicit.id, started_by=implicit.owner_id)
    assert await _dispatch(scheduler) == 1 and started == [bound.id]
    assert (await _entry(db, yes["task_run_id"])).attempt_count == 1
    assert (await _entry(db, no["task_run_id"])).last_error == "no_available_workers"


async def test_selected_worker_still_wins_and_other_wait_reason_never_bypassed(db, monkeypatch):
    from types import SimpleNamespace

    import app.scheduler.dispatch.loop as loop
    task, _ = await _bound(db)
    scheduler, started = _scheduler(db, monkeypatch)
    run = await scheduler.run_task_now(task.id, started_by=task.owner_id)
    worker = SimpleNamespace(id="selected-worker")
    claimed = []
    async def select_worker(*args, **kwargs):
        return worker, "selected"
    async def claim(db_, *, worker, queue_entry, task_run):
        claimed.append(worker.id)
        queue_entry.assigned_to = worker.id
    monkeypatch.setattr(loop, "select_dispatch_worker", select_worker)
    monkeypatch.setattr(loop, "claim_worker_assignment", claim)
    assert await _dispatch(scheduler) == 1 and claimed == [worker.id]
    assert (await _entry(db, run["task_run_id"])).assigned_to == worker.id
    other, _ = await _bound(db)
    scheduler, started = _scheduler(db, monkeypatch)
    await scheduler.run_task_now(other.id, started_by=other.owner_id)
    async def busy(*args, **kwargs):
        return None, "workers_busy"
    monkeypatch.setattr(loop, "select_dispatch_worker", busy)
    assert await _dispatch(scheduler) == 0 and started == []


async def test_redis_queue_uses_same_explicit_workflow_claim(db, monkeypatch):
    import app.services.redis_queue.service as redis_queue_service
    task, _ = await _bound(db)
    scheduler, started = _scheduler(db, monkeypatch)
    payload = await scheduler.run_task_now(task.id, started_by=task.owner_id)
    entry = await _entry(db, payload["task_run_id"])
    entry.queue_backend = "redis"
    await db.commit()
    pending = [{"entry_id": entry.id, "redis_url": "redis://fixture.invalid/0"}]
    removed = []
    async def pop(db_):
        return (pending.pop(0), "redis://fixture.invalid/0") if pending else (None, None)
    async def remove(entry_id, redis_url=None):
        removed.append(entry_id)
    monkeypatch.setattr(scheduler, "_pop_next_redis_queue_entry", pop)
    monkeypatch.setattr(redis_queue_service, "remove_task_queue_entry", remove)
    assert await _dispatch(scheduler) == 1
    assert started == [task.id] and removed == [entry.id]
    await db.refresh(entry)
    assert (entry.status, entry.attempt_count, entry.assigned_to) == ("in_progress", 1, None)


async def test_a_dispatched_run_is_referenced_until_it_ends_and_can_be_awaited():
    scheduler = TaskScheduler()
    release = asyncio.Event()
    ended = []

    async def dispatched_run():
        await release.wait()
        ended.append(True)

    task = scheduler._spawn_execution(dispatched_run())
    await asyncio.sleep(0)
    assert scheduler._execution_tasks == {task}
    release.set()
    await scheduler._wait_for_dispatched_runs()
    await asyncio.sleep(0)
    assert ended == [True] and scheduler._execution_tasks == set()
