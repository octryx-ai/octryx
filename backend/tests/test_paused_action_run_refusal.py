"""Contract: running a paused Action is a clear 409 refusal, never a 500 or a queued run.

``POST /admin/chat/api/panel/tasks/{id}/run`` maps the scheduler's typed refusal: an inactive
Action gives 409 ``action_paused`` with a fixed message, a missing one 404, and neither writes a
run or a queue entry. The scheduler keeps raising a ``ValueError`` (same message) for its other
callers, and ``allow_inactive`` callers still enqueue.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import func, select

from app.models import Project, Task, TaskQueueEntry, TaskRun, User
from app.scheduler import TaskScheduler
from app.scheduler.dispatch.backend import TASK_INACTIVE, TASK_NOT_FOUND, TaskNotRunnableError


@asynccontextmanager
async def _single_session(db):
    yield db


@pytest.fixture
def shared_session(db, monkeypatch):
    import app.db as database_module

    monkeypatch.setattr(database_module, "async_session_factory", lambda: _single_session(db))
    return db


async def _task(db, *, active: bool) -> Task:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"paused-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Nightly summary", task_type="agent_run",
                agent_type="diagnosis", owner_id=admin.id, is_active=active, config={"prompt": "Summarize"})
    db.add(task)
    await db.commit()
    return task


async def _writes(db, task_id: str) -> tuple[int, int]:
    runs = (await db.execute(select(func.count()).select_from(TaskRun).where(TaskRun.task_id == task_id))).scalar_one()
    entries = (await db.execute(
        select(func.count()).select_from(TaskQueueEntry).join(TaskRun, TaskRun.id == TaskQueueEntry.task_run_id)
        .where(TaskRun.task_id == task_id)
    )).scalar_one()
    return runs, entries


async def test_running_a_paused_action_is_a_409_with_a_fixed_message_and_no_side_effects(
    client, auth_headers, shared_session
):
    task = await _task(shared_session, active=False)
    response = await client.post(f"/admin/chat/api/panel/tasks/{task.id}/run", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "message": "This Action is paused. Resume it before running it.", "code": "action_paused",
    }
    assert await _writes(shared_session, task.id) == (0, 0)


async def test_running_a_missing_action_is_a_404(client, auth_headers, shared_session):
    response = await client.post(f"/admin/chat/api/panel/tasks/{uuid.uuid4()}/run", headers=auth_headers)
    assert response.status_code == 404


async def test_an_active_action_still_queues_one_run(client, auth_headers, shared_session):
    task = await _task(shared_session, active=True)
    response = await client.post(f"/admin/chat/api/panel/tasks/{task.id}/run", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert await _writes(shared_session, task.id) == (1, 1)


async def test_the_scheduler_refusal_is_typed_and_stays_a_value_error_for_other_callers(shared_session):
    scheduler = TaskScheduler()
    paused = await _task(shared_session, active=False)
    with pytest.raises(ValueError, match="not found or inactive") as refused:
        await scheduler.run_task_now(paused.id)
    assert isinstance(refused.value, TaskNotRunnableError) and refused.value.reason == TASK_INACTIVE
    with pytest.raises(TaskNotRunnableError) as missing:
        await scheduler.run_task_now(str(uuid.uuid4()))
    assert missing.value.reason == TASK_NOT_FOUND
    assert await _writes(shared_session, paused.id) == (0, 0)
    # The API run path that deliberately allows inactive tasks is unchanged.
    queued = await scheduler.run_task_now(paused.id, allow_inactive=True)
    assert queued["status"] == "queued" and await _writes(shared_session, paused.id) == (1, 1)
