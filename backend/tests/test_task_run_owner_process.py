"""Two platform processes at once (RollingUpdate overlap): task runs of a live process are never settled.

Contract: a locally claimed task run records its executing process; the scheduler's startup marks a running task
run stale only when that owner has no live lease (or the run has no owner); the ownership sweep ends an
owned run whose process is gone; a checkpointed session whose turn a live process runs is not "recovered".
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Task, TaskRun, User
from app.models.runtime.process_lease import RuntimeProcessLease
from app.scheduler import TaskScheduler
from app.services.runtime_ownership.interrupted_turns import TRIGGER_SWEEP, settle_interrupted_turns
from app.services.runtime_ownership.task_runs import ERROR_OWNER_GONE
from app.time_utils import utc_now


async def _lease(db: AsyncSession, *, live: bool) -> str:
    process_id, now = str(uuid.uuid4()), utc_now()
    expires = now + timedelta(minutes=5) if live else now - timedelta(minutes=5)
    db.add(RuntimeProcessLease(id=process_id, started_at=now - timedelta(hours=1), heartbeat_at=now,
                               expires_at=expires))
    await db.flush()
    return process_id


async def _running_runs(db: AsyncSession, owners: list[str | None]) -> list[TaskRun]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Owner check", description="", task_type="agent",
                agent_type="change", owner_id=admin.id, is_active=True, config={})
    db.add(task)
    await db.flush()
    runs = [TaskRun(id=str(uuid.uuid4()), task_id=task.id, trigger_type="schedule", status="running",
                    started_by=admin.id, input_={}, started_at=utc_now(), owner_process_id=owner)
            for owner in owners]
    db.add_all(runs)
    await db.commit()
    return runs


@pytest.mark.asyncio
async def test_scheduler_startup_leaves_the_runs_of_a_live_process_alone(db: AsyncSession) -> None:
    live, gone = await _lease(db, live=True), await _lease(db, live=False)
    of_live, of_gone, unowned = await _running_runs(db, [live, gone, None])

    await TaskScheduler()._mark_stale_running_runs(db)

    for run in (of_live, of_gone, unowned):
        await db.refresh(run)
    assert of_live.status == "running"
    assert (of_gone.status, unowned.status) == ("error", "error")
    assert of_gone.error == "Marked stale after scheduler startup"


@pytest.mark.asyncio
async def test_sweep_ends_owned_runs_whose_process_is_gone(db: AsyncSession) -> None:
    live, gone = await _lease(db, live=True), await _lease(db, live=False)
    of_live, of_gone, unowned = await _running_runs(db, [live, gone, None])

    settlement = await settle_interrupted_turns(db, trigger=TRIGGER_SWEEP)
    await db.commit()

    for run in (of_live, of_gone, unowned):
        await db.refresh(run)
    assert settlement.task_runs == 1
    assert (of_live.status, of_gone.status) == ("running", "error")
    assert of_gone.error == ERROR_OWNER_GONE and of_gone.completed_at is not None
    assert unowned.status == "running"  # no lease to ask: only the scheduler's startup settles it


@pytest.mark.asyncio
async def test_startup_recovery_skips_sessions_a_live_process_runs(db: AsyncSession, monkeypatch) -> None:
    from types import SimpleNamespace

    import app.scheduler.dispatch.registration as registration

    live, gone = await _lease(db, live=True), await _lease(db, live=False)
    of_live = SimpleNamespace(turn_owner_process_id=live, recovery_policy="auto_retry", run_status="in_progress")
    of_gone = SimpleNamespace(turn_owner_process_id=gone, recovery_policy="auto_retry", run_status="in_progress")

    async def recoverable(_db, limit=100):
        return [(of_live, object()), (of_gone, object())]

    monkeypatch.setattr(registration, "find_all_recoverable_sessions", recoverable)
    await TaskScheduler()._recover_interrupted_runs(db)

    assert of_live.run_status == "in_progress"
    assert of_gone.run_status is None
