"""Shared helpers for the test_scheduler_coordination_* modules."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.models import Project, Scheduler, SchedulerOwnerLease, Task, User
from app.scheduler import TaskScheduler
from app.time_utils import utc_now


class _Shared:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_exc):
        return None


def _factory(db):
    return lambda: _Shared(db)


async def _owner_id(db) -> str:
    return (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()


async def _task(db, *, schedule=None, active=True) -> Task:
    project = Project(name=f"coordination-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    task = Task(dispatch_binding="task_definition", name=f"t-{uuid.uuid4().hex[:6]}", task_type="agent_run", schedule=schedule, is_active=active,
                owner_id=await _owner_id(db), project_id=project.id, config={})
    db.add(task)
    await db.commit()
    return task


async def _scheduler(db, task, cron="*/5 * * * *", active=True) -> Scheduler:
    row = Scheduler(name=f"s-{uuid.uuid4().hex[:6]}", cron_expression=cron, task_id=task.id, is_active=active,
                    owner_id=task.owner_id)
    db.add(row)
    await db.commit()
    return row


async def _expire_lease(db):
    await db.execute(update(SchedulerOwnerLease).values(expires_at=utc_now() - timedelta(seconds=5)))
    await db.commit()


@pytest.fixture
async def coordinated(db):
    sched = TaskScheduler(session_factory=_factory(db))
    sched.scheduler.start(paused=True)
    try:
        yield sched
    finally:
        sched.scheduler.shutdown(wait=False)


def _jobs(sched) -> set[str]:
    return {job.id for job in sched.scheduler.get_jobs()}
