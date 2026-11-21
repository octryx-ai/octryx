"""Shared helpers for the test_scheduler_coordination_postgres_* modules."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Project, Scheduler, Task, TaskRun, User
from app.scheduler import TaskScheduler
from app.scheduler.coordination.fingerprint import scheduler_fingerprint
from tests.alembic_model_parity_support import migrated_database


async def _seed(maker):
    async with maker() as db:
        suffix = uuid.uuid4().hex[:10]
        user = User(username=f"coord-{suffix}", email=f"{suffix}@example.invalid", password_hash="not-a-login")
        project = Project(name=f"coordination-{suffix}")
        db.add_all([user, project])
        await db.flush()
        task = Task(dispatch_binding="task_definition", name="probe", task_type="agent_run", owner_id=user.id, project_id=project.id, is_active=True,
                    config={})
        db.add(task)
        await db.flush()
        row = Scheduler(name="probe", cron_expression="*/5 * * * *", task_id=task.id, is_active=True, owner_id=user.id)
        db.add(row)
        await db.commit()
        return task.id, row.id, scheduler_fingerprint(row)


async def _runs(maker, task_id) -> int:
    async with maker() as db:
        return (await db.execute(select(func.count(TaskRun.id)).where(TaskRun.task_id == task_id))).scalar_one()


async def _wait_blocked(maker, timeout: float = 15.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        async with maker() as db:
            blocked = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND cardinality(pg_blocking_pids(pid)) > 0"
                    )
                )
            ).scalar_one()
        if blocked:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("no session was blocked by a row lock")


async def _owner(maker, *, ttl=timedelta(seconds=90)) -> TaskScheduler:
    sched = TaskScheduler(session_factory=maker)
    sched._coordinator.ttl = ttl
    sched.scheduler.start(paused=True)
    await sched._coordinator.tick()
    assert sched._coordinator.epoch == 1, "the first insert owns epoch 1 at once"
    return sched


def _with_barrier(sched):
    """Pause a fire after it holds the lease (FOR SHARE) and the row locks, before its insert."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = sched._insert_task_run

    async def paused(*args, **kwargs):
        entered.set()
        await asyncio.wait_for(release.wait(), 20)
        return await original(*args, **kwargs)

    sched._insert_task_run = paused
    return entered, release


def _run(url, scenario):
    async def main():
        engine = create_async_engine(url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await scenario(maker)
        finally:
            await engine.dispose()

    asyncio.run(main())


def _scenario_test(scenario):
    def test(tmp_path):
        with migrated_database("postgresql", tmp_path) as database:
            _run(database.url, scenario)

    test.__name__ = f"test{scenario.__name__}"
    return test
