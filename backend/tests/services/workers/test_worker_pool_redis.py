"""The Redis queue backend enqueue and dispatch."""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

import app.db as database_module
import app.services.redis_queue.service as redis_queue_service
from app.models import AgentWorker, Project, Task, TaskQueueEntry, WorkerOnboarding, WorkerRuntimeState
from app.scheduler import TaskScheduler
from app.time_utils import utc_now


class FakeRedisQueue:
    def __init__(self):
        self.zset: dict[str, float] = {}
        self.payloads: dict[str, str] = {}

    async def ping(self):
        return True

    async def hset(self, _key: str, field: str, value: str):
        self.payloads[field] = value

    async def hget(self, _key: str, field: str):
        return self.payloads.get(field)

    async def hdel(self, _key: str, field: str):
        self.payloads.pop(field, None)

    async def zadd(self, _key: str, mapping: dict[str, float]):
        self.zset.update(mapping)

    async def zpopmin(self, _key: str, count: int = 1):
        if not self.zset:
            return []
        item = sorted(self.zset.items(), key=lambda pair: pair[1])[:count]
        for member, _score in item:
            self.zset.pop(member, None)
        return item

    async def zrem(self, _key: str, member: str):
        self.zset.pop(member, None)


def _redis_worker_and_task(project, admin):
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Redis Queue Alex",
        role="SRE",
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id, onboarding_status="ready", ready_at=utc_now(), warmup_period_hours=0
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id,
        status="active",
        current_priority="idle",
        active_tasks_count=0,
        max_parallel_tasks=1,
        available_slots=1,
    )
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Redis backed task",
        description="kubernetes incident",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"queue_priority": 9, "required_domain": "kubernetes"},
    )
    return worker, task


def _stub_queue_scheduler(monkeypatch, db):
    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    scheduler._max_parallel_queue_tasks = 1
    seen: list[tuple[str | None, str | None]] = []

    async def fake_execute_task(
        task_id: str,
        trigger_type: str = "manual",
        trigger_id: str | None = None,
        task_run_id: str | None = None,
        assigned_worker_id: str | None = None,
        queue_domain: str | None = None,
    ):
        seen.append((assigned_worker_id, queue_domain))

    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_execute_task", fake_execute_task)

    async def noop_ensure_dispatcher():
        return None

    monkeypatch.setattr(scheduler, "_ensure_queue_dispatcher_running", noop_ensure_dispatcher)
    return scheduler, seen


def _store_in_fake_redis(fake_redis, entry_id, payload, priority):
    fake_redis.payloads[entry_id] = json.dumps(payload)
    fake_redis.zset[entry_id] = float((10 - int(priority or 5)) * 10_000_000_000_000)


def _stub_redis_queue(monkeypatch, fake_redis, pop_urls, remove_urls):
    async def fake_available(redis_url=None):
        return True

    async def fake_enqueue(
        *,
        entry_id: str,
        project_id: str | None,
        task_run_id: str,
        task_id: str,
        priority: int,
        queued_at,
        required_domain: str | None,
        required_worker_id: str | None,
        redis_url: str | None = None,
    ):
        payload = {
            "entry_id": entry_id,
            "project_id": project_id,
            "task_run_id": task_run_id,
            "task_id": task_id,
            "priority": priority,
            "queued_at": queued_at.isoformat() if queued_at else None,
            "required_domain": required_domain,
            "required_worker_id": required_worker_id,
            "redis_url": redis_url,
        }
        _store_in_fake_redis(fake_redis, entry_id, payload, priority)
        return True

    async def fake_pop(**kwargs):
        pop_urls.append(kwargs.get("redis_url"))
        popped = await fake_redis.zpopmin("ignored", count=1)
        if not popped:
            return None
        entry_id = popped[0][0]
        payload = fake_redis.payloads.get(entry_id)
        return json.loads(payload) if payload else {"entry_id": entry_id}

    async def fake_requeue(entries, **kwargs):
        for entry in entries:
            _store_in_fake_redis(fake_redis, entry["entry_id"], entry, entry.get("priority"))

    async def fake_remove(entry_id, **kwargs):
        remove_urls.append(kwargs.get("redis_url"))
        await fake_redis.zrem("ignored", entry_id)
        await fake_redis.hdel("ignored", entry_id)

    monkeypatch.setattr(redis_queue_service, "is_redis_queue_available", fake_available)
    monkeypatch.setattr(redis_queue_service, "enqueue_task_queue_entry", fake_enqueue)
    monkeypatch.setattr(redis_queue_service, "pop_next_task_queue_entry", fake_pop)
    monkeypatch.setattr(redis_queue_service, "requeue_task_queue_entries", fake_requeue)
    monkeypatch.setattr(redis_queue_service, "remove_task_queue_entry", fake_remove)


@pytest.mark.asyncio
async def test_scheduler_redis_backend_enqueue_and_dispatch(db, monkeypatch, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker, task = _redis_worker_and_task(project, auth_user)
    db.add_all([worker, task])
    await db.commit()

    fake_redis = FakeRedisQueue()
    scheduler, seen = _stub_queue_scheduler(monkeypatch, db)
    pop_urls: list[str | None] = []
    remove_urls: list[str | None] = []
    _stub_redis_queue(monkeypatch, fake_redis, pop_urls, remove_urls)

    from app.services.worker_pool.state import get_or_create_worker_pool_config

    pool = await get_or_create_worker_pool_config(db, project.id)
    pool.queue_backend = "redis"
    pool.redis_url = "redis://fake"
    await db.commit()

    payload = await scheduler.run_task_now(task.id, started_by=auth_user.id)
    queue_entry = (
        await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == payload["task_run_id"]))
    ).scalar_one()
    assert queue_entry.queue_backend == "redis"
    assert queue_entry.id in fake_redis.zset

    dispatched = await scheduler._dispatch_queued_runs_once()
    assert dispatched == 1
    await asyncio.sleep(0)
    await db.refresh(queue_entry)
    assert queue_entry.assigned_to == worker.id
    assert queue_entry.status == "in_progress"
    assert seen == [(worker.id, "kubernetes")]
    assert queue_entry.id not in fake_redis.zset
    assert pop_urls == ["redis://fake"]
    assert remove_urls == ["redis://fake"]
