"""State that crosses process boundaries once the API and the worker run apart.

A turn or task run may execute in another process (a sibling API process, the platform worker):
its "running" state, a user stop, a task-run cancel and a manual "run now" must still behave as
in one process. These tests play both processes in one interpreter by switching the process id.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.runtime_ownership.process_identity as process_identity
from app.models import AuditLog, Project, Task, TaskQueueEntry, TaskRun, User
from app.models import Session as AgentSession
from app.scheduler import TaskScheduler
from app.services.session.remote_stop import STOP_REQUEST_ACTION, RemoteTurnStopWatcher
from app.services.session.turn_stop import stop_session_turn
from app.services.session.turn_tasks import CHAT_RUN_TASKS, effective_session_status, register_turn_task
from app.time_utils import utc_now


class _SharedSessions:
    """A session factory that hands out the test's own session (its transaction stays the test's)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self) -> AsyncSession:
        return self._db

    async def __aexit__(self, *exc) -> bool:
        return False


def _as_process(monkeypatch, process_id: str) -> None:
    import os

    monkeypatch.setattr(process_identity, "_identity", (os.getpid(), process_id))


async def _running_session(db: AsyncSession, *, owner: str) -> AgentSession:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = AgentSession(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="running",
                           metadata_={"run_status": "in_progress", "current_turn_started_at": "2026-11-07T08:00:00"},
                           turn_owner_process_id=owner)
    db.add(session)
    await db.commit()
    return session


def test_a_turn_owned_by_another_process_reads_running(monkeypatch) -> None:
    _as_process(monkeypatch, "api-1")
    elsewhere = AgentSession(id="s1", status="running", turn_owner_process_id="worker-1")
    here_stale = AgentSession(id="s2", status="running", turn_owner_process_id="api-1")
    legacy = AgentSession(id="s3", status="running", turn_owner_process_id=None)
    assert effective_session_status(elsewhere) == "running"
    assert effective_session_status(here_stale) == "active"  # this process has no task for it: stale
    assert effective_session_status(legacy) == "active"


@pytest.mark.asyncio
async def test_a_stop_in_one_process_cancels_the_turn_running_in_another(db: AsyncSession, monkeypatch) -> None:
    session = await _running_session(db, owner="worker-1")

    # Process "worker-1" runs the turn.
    _as_process(monkeypatch, "worker-1")
    turn = asyncio.create_task(asyncio.sleep(60))
    register_turn_task(session.id, turn)
    watcher = RemoteTurnStopWatcher(_SharedSessions(db))
    assert await watcher.check_once() == []  # nothing requested yet

    # Process "api-1" serves the stop: it has no task, so it records a request for the owner.
    _as_process(monkeypatch, "api-1")
    CHAT_RUN_TASKS.pop(session.id)  # one interpreter plays both processes: hide worker-1's registry entry
    await stop_session_turn(db, session)
    register_turn_task(session.id, turn)
    requests = (await db.execute(select(AuditLog).where(AuditLog.action == STOP_REQUEST_ACTION))).scalars().all()
    assert [(r.resource_id, r.details["owner_process_id"]) for r in requests] == [(session.id, "worker-1")]
    assert turn.done() is False
    assert await watcher.check_once() == []  # another process's watcher leaves the turn alone

    # Back in "worker-1": its watcher cancels the turn once, and only once.
    _as_process(monkeypatch, "worker-1")
    assert await watcher.check_once() == [session.id]
    with pytest.raises(asyncio.CancelledError):
        await turn
    assert await watcher.check_once() == []
    CHAT_RUN_TASKS.pop(session.id, None)


@pytest.mark.asyncio
async def test_a_stop_request_for_an_earlier_turn_never_cancels_the_next(db: AsyncSession, monkeypatch) -> None:
    session = await _running_session(db, owner="worker-1")
    _as_process(monkeypatch, "api-1")
    await stop_session_turn(db, session)

    # The next turn of the session started in "worker-1" before its watcher saw the old request.
    _as_process(monkeypatch, "worker-1")
    session.status = "running"
    session.metadata_ = {"run_status": "in_progress", "current_turn_started_at": "2026-11-07T09:00:00"}
    await db.commit()
    turn = asyncio.create_task(asyncio.sleep(60))
    register_turn_task(session.id, turn)
    try:
        assert await RemoteTurnStopWatcher(_SharedSessions(db)).check_once() == []
        assert turn.done() is False
    finally:
        turn.cancel()
        CHAT_RUN_TASKS.pop(session.id, None)


@pytest.mark.asyncio
async def test_a_local_stop_records_no_request(db: AsyncSession, monkeypatch) -> None:
    _as_process(monkeypatch, "api-1")
    session = await _running_session(db, owner="api-1")
    turn = asyncio.create_task(asyncio.sleep(60))
    register_turn_task(session.id, turn)

    await stop_session_turn(db, session)

    assert turn.cancelled() is True
    assert (await db.execute(select(AuditLog).where(AuditLog.action == STOP_REQUEST_ACTION))).first() is None
    CHAT_RUN_TASKS.pop(session.id, None)


async def _queued_run(db: AsyncSession) -> tuple[Task, TaskRun, TaskQueueEntry]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Split check", description="", task_type="agent",
                agent_type="change", owner_id=admin.id, is_active=True, config={})
    db.add(task)
    await db.flush()
    run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, trigger_type="manual", status="queued",
                  started_by=admin.id, input_={})
    db.add(run)
    await db.flush()
    entry = TaskQueueEntry(id=str(uuid.uuid4()), task_run_id=run.id, project_id=project.id,
                           status="pending", queue_backend="database", queued_at=utc_now())
    db.add(entry)
    await db.commit()
    return task, run, entry


@pytest.mark.asyncio
async def test_run_now_claims_the_queued_run_so_the_dispatcher_never_starts_it_too(db: AsyncSession) -> None:
    task, run, entry = await _queued_run(db)
    api = TaskScheduler(session_factory=_SharedSessions(db))

    assert await api.claim_queued_run(run.id) is True
    assert await api.claim_queued_run(run.id) is False  # a second claimant (the dispatcher) loses

    await db.refresh(run)
    await db.refresh(entry)
    assert (run.status, entry.status) == ("running", "in_progress")
    assert entry.started_at is not None and run.owner_process_id

    # The platform worker's dispatcher no longer sees it.
    worker = TaskScheduler(session_factory=_SharedSessions(db))
    started: list[str] = []

    async def _record(task_id, **kwargs):
        started.append(kwargs.get("task_run_id"))

    worker._execute_task = _record
    assert await worker._dispatch_queued_runs_once() == 0
    assert started == []


@pytest.mark.asyncio
async def test_a_run_cancelled_in_the_database_is_cancelled_where_it_executes(db: AsyncSession) -> None:
    task, run, _entry = await _queued_run(db)
    worker = TaskScheduler(session_factory=_SharedSessions(db))
    execution = asyncio.create_task(asyncio.sleep(60))
    worker._running_futures[task.id] = execution
    worker._active_task_ids.add(task.id)
    worker._running_task_run_ids[task.id] = run.id

    assert await worker._cancel_runs_cancelled_elsewhere() == []  # still queued/running: left alone

    run.status = "cancelled"  # what the API's cancel endpoint writes
    await db.commit()
    assert await worker._cancel_runs_cancelled_elsewhere() == [task.id]
    with pytest.raises(asyncio.CancelledError):
        await execution
    assert task.id not in worker._active_task_ids


@pytest.mark.asyncio
async def test_scheduler_jobs_are_read_from_the_owner_acknowledgements(db: AsyncSession) -> None:
    from datetime import timedelta

    from app.models import SchedulerJobApplication, SchedulerOwnerLease
    from app.scheduler.coordination.registered_jobs import registered_jobs_from_database

    assert await registered_jobs_from_database(db) == []  # no live owner: nothing registered
    now = utc_now()
    db.add(SchedulerOwnerLease(id="task-scheduler", owner_process_id="worker-1", epoch=3, acquired_at=now,
                               heartbeat_at=now, expires_at=now + timedelta(minutes=5)))
    db.add(SchedulerJobApplication(job_key="task:t1", owner_epoch=3, applied_fingerprint="f", status="registered",
                                   next_run_at=now + timedelta(hours=1), timezone="UTC", applied_at=now))
    db.add(SchedulerJobApplication(job_key="task:t0", owner_epoch=2, applied_fingerprint="f", status="registered",
                                   next_run_at=now, timezone="UTC", applied_at=now))
    await db.commit()

    jobs = await registered_jobs_from_database(db)
    assert [(job["id"], job["timezone"]) for job in jobs] == [("task_t1", "UTC")]
