"""The guarded fire enqueues only for the lease owner and the unchanged active row, Redis pushes follow the commit, and worker_application is acknowledged only for what the scheduler holds."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

import app.services.redis_queue.service as redis_queue_service
from app.models import SchedulerJobApplication, SchedulerOwnerLease, TaskQueueEntry, TaskRun
from app.scheduler import TaskScheduler
from app.scheduler.coordination import owner_lease
from app.scheduler.coordination.application_status import scheduler_worker_applications
from app.scheduler.coordination.fingerprint import scheduler_fingerprint, task_fingerprint
from app.services.admin.provider.admin_scheduler_service import create_scheduler, list_schedulers
from app.services.runtime_ownership.process_identity import current_process_id
from app.time_utils import utc_now
from tests.scheduler.scheduler_coordination_support import (  # noqa: F401
    _expire_lease,
    _factory,
    _jobs,
    _scheduler,
    _task,
    coordinated,
)

# ---- guarded fire ----------------------------------------------------------------------------------


async def _runs(db, task) -> list[TaskRun]:
    task_id = task if isinstance(task, str) else task.id
    return list((await db.execute(select(TaskRun).where(TaskRun.task_id == task_id))).scalars())


async def test_guarded_fire_enqueues_only_for_the_owner_and_the_unchanged_active_row(db, coordinated):  # noqa: F811
    task = await _task(db, schedule="*/5 * * * *")
    row = await _scheduler(db, task)
    await coordinated._coordinator.tick()
    fp = scheduler_fingerprint(row)

    payload = await coordinated._fire_scheduled("scheduler", fp, task.id, "scheduler", row.id)
    assert payload["status"] == "queued"
    runs = await _runs(db, task)
    assert [(r.trigger_type, r.trigger_id, r.status) for r in runs] == [("scheduler", row.id, "queued")]
    entry = (await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == runs[0].id))).scalar_one()
    assert entry.queue_backend == "database"

    task_payload = await coordinated._fire_scheduled("task", task_fingerprint(task), task.id, "schedule")
    assert task_payload["status"] == "queued"
    assert sorted(r.trigger_type for r in await _runs(db, task)) == ["schedule", "scheduler"]

    row_id, task_id = row.id, task.id

    async def fire():
        result = await coordinated._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id)
        await db.refresh(row)
        await db.refresh(task)
        return result

    row.cron_expression = "*/9 * * * *"
    await db.commit()
    assert await fire() is None, "stale content"
    row.cron_expression = "*/5 * * * *"
    row.is_active = False
    await db.commit()
    assert await fire() is None, "paused"
    row.is_active = True
    task.is_active = False
    await db.commit()
    assert await fire() is None, "task inactive"
    task.is_active = True
    await db.commit()
    await db.delete(row)
    await db.commit()
    assert await coordinated._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id) is None, "deleted"
    assert len(await _runs(db, task_id)) == 2


async def test_a_fire_without_the_lease_writes_nothing(db, coordinated):  # noqa: F811
    task = await _task(db)
    row = await _scheduler(db, task)
    await coordinated._coordinator.tick()
    await _expire_lease(db)
    fp, task_id, row_id = scheduler_fingerprint(row), task.id, row.id
    assert await coordinated._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id) is None
    assert coordinated._coordinator.epoch is None and _jobs(coordinated) == set()
    assert await _runs(db, task_id) == []


async def test_fire_updates_the_acknowledged_next_run(db, coordinated):  # noqa: F811
    task = await _task(db)
    row = await _scheduler(db, task)
    await coordinated._coordinator.tick()
    ack = await db.get(SchedulerJobApplication, f"scheduler:{row.id}")
    ack.next_run_at = utc_now() - timedelta(hours=2)
    await db.commit()
    assert (await scheduler_worker_applications(db, [row]))[row.id]["status"] == "pending", "a stale next run is not current"
    await coordinated._fire_scheduled("scheduler", scheduler_fingerprint(row), task.id, "scheduler", row.id)
    await db.refresh(ack)
    assert ack.next_run_at > utc_now()
    assert (await scheduler_worker_applications(db, [row]))[row.id]["status"] == "applied"


async def test_redis_push_happens_after_insert_and_a_failed_push_keeps_the_row(db, coordinated, monkeypatch):  # noqa: F811
    from app.models import WorkerPoolConfig

    task = await _task(db)
    db.add(WorkerPoolConfig(project_id=task.project_id, queue_backend="redis", redis_url="redis://fake"))
    await db.commit()
    row = await _scheduler(db, task)
    await coordinated._coordinator.tick()

    async def available(_url):
        return True

    async def failing_push(**_kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis_queue_service, "is_redis_queue_available", available)
    monkeypatch.setattr(redis_queue_service, "enqueue_task_queue_entry", failing_push)
    payload = await coordinated._fire_scheduled("scheduler", scheduler_fingerprint(row), task.id, "scheduler", row.id)
    assert payload["status"] == "queued"
    entry = (await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.id == payload["queue_entry_id"]))).scalar_one()
    assert (entry.queue_backend, entry.status) == ("redis", "pending"), "committed row stays for the next start's resync"


# ---- read model and API ----------------------------------------------------------------------------


async def test_worker_application_matrix_and_batched_reads(db, coordinated):  # noqa: F811
    task = await _task(db)
    rows = [await _scheduler(db, task) for _ in range(5)]
    paused = await _scheduler(db, task, active=False)
    statuses = await scheduler_worker_applications(db, [*rows, paused])
    assert {s["status"] for s in statuses.values() if s} == {"worker_unavailable", "paused"}
    await coordinated._coordinator.tick()
    statuses = await scheduler_worker_applications(db, [rows[0], paused])
    applied = statuses[rows[0].id]
    assert applied["status"] == "applied" and applied["next_run_at"].endswith("Z") and applied["timezone"]
    assert set(applied) == {"status", "next_run_at", "timezone"}, "no process id, epoch or other internals"
    assert statuses[paused.id] == {"status": "paused", "next_run_at": None, "timezone": None}

    rows[0].cron_expression = "*/11 * * * *"
    await db.commit()
    assert (await scheduler_worker_applications(db, [rows[0]]))[rows[0].id]["status"] == "pending", "other content"
    await _expire_lease(db)
    assert (await scheduler_worker_applications(db, [rows[1]]))[rows[1].id]["status"] == "worker_unavailable"
    assert await owner_lease.acquire_owner_lease(db, process_id="successor") == 2
    assert (await scheduler_worker_applications(db, [rows[1]]))[rows[1].id]["status"] == "pending", "old epoch"

    statements: list[str] = []

    def _count(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    sa_event.listen(Engine, "before_cursor_execute", _count)
    try:
        await scheduler_worker_applications(db, rows[:1])
        one = len(statements)
        statements.clear()
        await scheduler_worker_applications(db, rows)
        assert len(statements) == one, "one batch for any number of rows"
    finally:
        sa_event.remove(Engine, "before_cursor_execute", _count)


async def test_scheduler_api_adds_worker_application_and_keeps_existing_fields(db):
    task = await _task(db)
    created = await create_scheduler(db, user_id=task.owner_id,
                                     payload={"name": "Nightly", "cron_expression": "0 2 * * *", "task_id": task.id})
    assert {"id", "name", "description", "cron_expression", "task_id", "task_name", "is_active", "owner_id",
            "created_at"} <= set(created)
    assert created["worker_application"]["status"] in {"pending", "worker_unavailable"}
    listed = next(row for row in await list_schedulers(db) if row["id"] == created["id"])
    assert listed["worker_application"] == {"status": "worker_unavailable", "next_run_at": None, "timezone": None}


async def test_api_only_task_scheduler_registers_nothing_and_takes_no_lease(db):
    sched = TaskScheduler(session_factory=_factory(db))
    task = await _task(db, schedule="*/5 * * * *")
    await _scheduler(db, task)
    sched.request_reconcile()
    assert sched.scheduler.get_jobs() == []
    assert (await db.execute(select(func.count()).select_from(SchedulerOwnerLease))).scalar_one() == 0
    assert current_process_id()


async def test_an_unknown_acknowledgement_status_never_reads_applied(db, coordinated):  # noqa: F811
    task = await _task(db)
    row = await _scheduler(db, task)
    await coordinated._coordinator.tick()
    assert (await scheduler_worker_applications(db, [row]))[row.id]["status"] == "applied"
    ack = await db.get(SchedulerJobApplication, f"scheduler:{row.id}")
    ack.status = "something_else"
    await db.commit()
    assert (await scheduler_worker_applications(db, [row]))[row.id] == {
        "status": "pending", "next_run_at": None, "timezone": None}


async def test_a_job_apscheduler_does_not_hold_is_not_acknowledged(db, coordinated, monkeypatch):  # noqa: F811
    task = await _task(db)
    row = await _scheduler(db, task)
    monkeypatch.setattr(coordinated, "_register_job", lambda record: None)
    await coordinated._coordinator.tick()
    assert coordinated._coordinator.registered_fingerprints() == {}, "retried on the next pass"
    assert await db.get(SchedulerJobApplication, f"scheduler:{row.id}") is None
    assert (await scheduler_worker_applications(db, [row]))[row.id]["status"] == "pending"
    monkeypatch.undo()
    await coordinated._coordinator.reconcile_once()
    assert (await scheduler_worker_applications(db, [row]))[row.id]["status"] == "applied"
