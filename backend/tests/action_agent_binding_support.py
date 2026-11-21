"""Shared helpers for the test_action_agent_binding_* modules."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from app.models import Task, TaskQueueEntry
from app.scheduler import TaskScheduler
from tests.test_action_runtime_admission import _admin, _agent, _single_session

BOUND = "agent_definition"


# --- dispatch ---------------------------------------------------------------------------------------------


async def _dispatch(scheduler) -> int:
    dispatched = await scheduler._dispatch_queued_runs_once()
    await asyncio.sleep(0)  # let the spawned (fake) executions record themselves
    return dispatched


def _scheduler(db, monkeypatch, *, slots=2):
    import app.db as database_module

    scheduler = TaskScheduler()
    scheduler._max_parallel_queue_tasks = slots
    started: list[str] = []

    async def fake_execute_task(task_id, **_kwargs):
        started.append(task_id)

    monkeypatch.setattr(database_module, "async_session_factory", lambda: _single_session(db))
    monkeypatch.setattr(scheduler, "_execute_task", fake_execute_task)
    return scheduler, started


async def _task(db, project, *, binding):
    admin = await _admin(db)
    agent = await _agent(db, admin.id, project.id)
    task = Task(id=str(uuid.uuid4()), project_id=project.id, name="Nightly summary", task_type="agent_run",
                agent_type="diagnosis", owner_id=admin.id, is_active=True,
                config={"agent_definition_id": agent.id}, dispatch_binding=binding)
    db.add(task)
    await db.commit()
    return task


async def _entry(db, run_id) -> TaskQueueEntry:
    entry = (await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == run_id))).scalar_one()
    await db.refresh(entry)
    return entry


async def bound_action_fields(db, project_id: str) -> dict:
    """The fields a panel create needs to bind a new Action to a fresh, runnable agent of the admin."""
    admin = await _admin(db)
    agent = await _agent(db, admin.id, project_id)
    await db.commit()
    return {"dispatch_binding": BOUND, "config": {"agent_definition_id": agent.id}}
