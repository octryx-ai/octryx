"""The database and Redis dispatch branches claim a bound run locally, leave task-definition runs waiting for a worker,
and leave an available worker's accounting intact."""

from __future__ import annotations

import uuid

import app.services.redis_queue.service as redis_queue_service
from app.models import AgentWorker, TaskQueueEntry, TaskRun
from app.models.worker.worker import WorkerOnboarding, WorkerRuntimeState
from app.services.admin.task import _admin_task_management as admin_tasks
from app.time_utils import utc_now
from tests.action_agent_binding_support import BOUND, _dispatch, _entry, _scheduler, _task
from tests.scheduler.test_action_runtime_admission import _project


async def test_database_branch_claims_bound_runs_locally_and_keeps_legacy_waiting(db, monkeypatch):
    project = await _project(db)
    bound, legacy = await _task(db, project, binding=BOUND), await _task(db, project, binding="task_definition", worker_step=True)
    scheduler, started = _scheduler(db, monkeypatch)
    bound_run = await scheduler.run_task_now(bound.id, started_by=bound.owner_id)
    legacy_run = await scheduler.run_task_now(legacy.id, started_by=legacy.owner_id)

    assert await _dispatch(scheduler) == 1
    assert started == [bound.id]
    claimed = await _entry(db, bound_run["task_run_id"])
    assert (claimed.status, claimed.assigned_to, claimed.attempt_count) == ("in_progress", None, 1)
    waiting = await _entry(db, legacy_run["task_run_id"])
    assert (waiting.status, waiting.last_error, waiting.attempt_count) == ("pending", "no_available_workers", 0)


async def test_capacity_same_task_and_cancellation_still_bound_local_claims(db, monkeypatch):
    project = await _project(db)
    tasks = [await _task(db, project, binding=BOUND) for _ in range(3)]
    scheduler, started = _scheduler(db, monkeypatch, slots=2)
    for task in tasks:
        await scheduler.run_task_now(task.id, started_by=task.owner_id)
    assert await _dispatch(scheduler) == 2, "two of three within capacity"

    same = await _task(db, project, binding=BOUND)
    scheduler, started = _scheduler(db, monkeypatch, slots=5)
    scheduler._active_task_ids = set()
    first = await scheduler.run_task_now(same.id, started_by=same.owner_id)
    second_run = TaskRun(id=str(uuid.uuid4()), task_id=same.id, status="queued", trigger_type="manual",
                         started_by=same.owner_id, input_={})
    db.add(second_run)
    db.add(TaskQueueEntry(id=str(uuid.uuid4()), task_run_id=second_run.id, project_id=project.id, status="pending",
                          queue_backend="database", queued_at=utc_now()))
    await db.commit()
    await _dispatch(scheduler)
    assert started.count(same.id) == 1, "one run per task at a time"
    assert (await _entry(db, second_run.id)).status == "pending"
    assert (await _entry(db, first["task_run_id"])).status == "in_progress"

    cancelled = await _task(db, project, binding=BOUND)
    scheduler, started = _scheduler(db, monkeypatch, slots=5)
    run = await scheduler.run_task_now(cancelled.id, started_by=cancelled.owner_id)
    await admin_tasks.cancel_task_run(db, task_id=cancelled.id, run_id=run["task_run_id"])
    await _dispatch(scheduler)
    assert cancelled.id not in started


async def test_redis_branch_has_the_same_bound_and_legacy_outcomes(db, monkeypatch):
    project = await _project(db)
    bound, legacy = await _task(db, project, binding=BOUND), await _task(db, project, binding="task_definition", worker_step=True)
    scheduler, started = _scheduler(db, monkeypatch)
    runs = [await scheduler.run_task_now(task.id, started_by=task.owner_id) for task in (bound, legacy)]
    entries = [await _entry(db, run["task_run_id"]) for run in runs]
    for entry in entries:
        entry.queue_backend = "redis"
    await db.commit()
    payloads = [{"entry_id": entry.id, "redis_url": "redis://queue.invalid/0"} for entry in entries]
    removed, requeued = [], []

    async def pop(_db):
        return (payloads.pop(0), "redis://queue.invalid/0") if payloads else (None, None)

    async def remove(entry_id, redis_url=None):
        removed.append(entry_id)

    async def requeue(items, redis_url=None):
        requeued.extend(item["entry_id"] for item in items)

    monkeypatch.setattr(scheduler, "_pop_next_redis_queue_entry", pop)
    monkeypatch.setattr(redis_queue_service, "remove_task_queue_entry", remove)
    monkeypatch.setattr(redis_queue_service, "requeue_task_queue_entries", requeue)

    assert await _dispatch(scheduler) == 1
    assert started == [bound.id] and removed == [entries[0].id] and requeued == [entries[1].id]
    assert (await _entry(db, runs[0]["task_run_id"])).status == "in_progress"
    waiting = await _entry(db, runs[1]["task_run_id"])
    assert (waiting.status, waiting.last_error) == ("pending", "no_available_workers")


async def test_an_available_worker_still_takes_a_bound_run_with_its_accounting(db, monkeypatch):
    project = await _project(db)
    worker = AgentWorker(id=str(uuid.uuid4()), project_id=project.id, name="Ops", role="ops", is_active=True)
    worker.onboarding = WorkerOnboarding(worker_id=worker.id, onboarding_status="ready", ready_at=utc_now(),
                                         warmup_period_hours=0)
    worker.runtime_state = WorkerRuntimeState(worker_id=worker.id, status="active", current_priority="idle",
                                              active_tasks_count=0, max_parallel_tasks=1, available_slots=1)
    db.add(worker)
    await db.commit()
    bound = await _task(db, project, binding=BOUND)
    scheduler, started = _scheduler(db, monkeypatch)
    run = await scheduler.run_task_now(bound.id, started_by=bound.owner_id)
    assert await _dispatch(scheduler) == 1
    assert (await _entry(db, run["task_run_id"])).assigned_to == worker.id


async def test_a_legacy_agent_run_without_steps_runs_on_the_runner_pool_without_a_worker(db, monkeypatch):
    project = await _project(db)
    legacy = await _task(db, project, binding="task_definition")
    scheduler, started = _scheduler(db, monkeypatch)
    await scheduler.run_task_now(legacy.id, started_by=legacy.owner_id)
    assert await _dispatch(scheduler) == 1 and started == [legacy.id]  # never waits for a worker profile
