"""Queue backend and enqueue helpers for the task scheduler."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func

from app.services.worker_pool.helpers import infer_required_domain
from app.services.worker_pool.state import get_or_create_worker_pool_config, worker_pool_config_generation

from ...services.redis_queue import service as redis_queue_service
from ...services.runtime_ownership.process_identity import current_process_id
from ...time_utils import utc_now

logger = logging.getLogger(__name__)

#: How long the dispatcher reuses the Workspaces' Redis queue URLs. It polls every 0.75 s and these settings change
#: rarely (otherwise ``worker_pool_config`` is read hundreds of thousands of times in a few days); a change made in
#: this process applies at once.
REDIS_QUEUE_URLS_TTL_SECONDS = 15.0

TASK_NOT_FOUND = "not_found"
TASK_INACTIVE = "inactive"
TASK_WORKSPACE_REQUIRED = "workspace_required"  # no worker pool, queue or run without the Action's Workspace
_NOT_RUNNABLE_MESSAGES = {
    TASK_WORKSPACE_REQUIRED: "Task {task_id} has no Workspace; choose the Workspace this Action runs in",
}


class TaskNotRunnableError(ValueError):
    def __init__(self, task_id: str, reason: str) -> None:
        self.task_id = task_id
        self.reason = reason
        super().__init__(_NOT_RUNNABLE_MESSAGES.get(reason, "Task {task_id} not found or inactive")
                         .format(task_id=task_id))


@dataclass(frozen=True)
class QueueBackendDecision:
    backend: str
    redis_url: str | None
    last_error: str | None




class SchedulerDispatchBackendMixin:
    """Queue backend synchronization and enqueue helpers."""

    async def _ensure_queue_dispatcher_running(self) -> None:
        self._queue_stop_event.clear()
        if self._queue_dispatch_task is None or self._queue_dispatch_task.done():
            self._queue_dispatch_task = asyncio.create_task(self._queue_dispatch_loop(), name="task-queue-dispatcher")

    async def _sync_redis_queue_backend(self) -> None:
        from sqlalchemy import select

        from ...models import Task, TaskQueueEntry, TaskRun, WorkerPoolConfig

        session_factory = self._get_session_factory()
        async with session_factory() as db:
            config_rows = (
                await db.execute(
                    select(WorkerPoolConfig.project_id, WorkerPoolConfig.redis_url).where(
                        WorkerPoolConfig.queue_backend == "redis"
                    )
                )
            ).all()
            redis_urls_by_project = {
                str(project_id): str(redis_url or "").strip()
                for project_id, redis_url in config_rows
                if str(redis_url or "").strip()
            }
            rows = (
                await db.execute(
                    select(TaskQueueEntry, TaskRun, Task)
                    .join(TaskRun, TaskRun.id == TaskQueueEntry.task_run_id)
                    .join(Task, Task.id == TaskRun.task_id)
                    .where(
                        TaskQueueEntry.queue_backend == "redis",
                        TaskQueueEntry.status == "pending",
                        TaskQueueEntry.started_at.is_(None),
                        TaskQueueEntry.completed_at.is_(None),
                        TaskRun.status == "queued",
                    )
                )
            ).all()
            payloads_by_url: dict[str, list[dict[str, object]]] = {}
            for queue_entry, task_run, task in rows:
                redis_url = redis_urls_by_project.get(str(queue_entry.project_id or task.project_id or ""))
                if not redis_url:
                    continue
                payloads_by_url.setdefault(redis_url, []).append(
                    {
                        "entry_id": queue_entry.id,
                        "project_id": queue_entry.project_id,
                        "task_run_id": task_run.id,
                        "task_id": task.id,
                        "priority": queue_entry.priority,
                        "queued_at": queue_entry.queued_at,
                        "required_domain": queue_entry.required_domain,
                        "required_worker_id": queue_entry.required_worker_id,
                        "redis_url": redis_url,
                    }
                )
            for redis_url, batch in payloads_by_url.items():
                sync_pending = redis_queue_service.sync_pending_task_queue_entries
                await sync_pending(batch, redis_url=redis_url)

    async def _configured_redis_queue_urls(self, db) -> list[str]:
        from sqlalchemy import select

        from ...models import WorkerPoolConfig

        generation = worker_pool_config_generation()
        now = time.monotonic()
        cached = getattr(self, "_redis_queue_urls_cache", None)
        if cached is not None and cached[0] == generation and now - cached[1] < REDIS_QUEUE_URLS_TTL_SECONDS:
            return list(cached[2])
        rows = (
            await db.execute(
                select(WorkerPoolConfig.redis_url).where(
                    WorkerPoolConfig.queue_backend == "redis",
                    WorkerPoolConfig.redis_url.is_not(None),
                )
            )
        ).all()
        urls = [str(row[0] or "").strip() for row in rows if str(row[0] or "").strip()]
        self._redis_queue_urls_cache = (generation, now, tuple(urls))
        return urls

    async def _list_active_redis_queue_urls(self, db) -> list[str]:
        from ...config import get_settings

        urls = await self._configured_redis_queue_urls(db)
        fallback = str(get_settings().redis_url or "").strip()
        if fallback:
            urls.append(fallback)
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                deduped.append(url)
        return deduped

    async def _pop_next_redis_queue_entry(self, db) -> tuple[dict | None, str | None]:
        redis_urls = await self._list_active_redis_queue_urls(db)
        if not redis_urls:
            return None, None
        start_index = self._redis_queue_cursor % len(redis_urls)
        ordered_urls = redis_urls[start_index:] + redis_urls[:start_index]
        for offset, redis_url in enumerate(ordered_urls, start=1):
            pop_next = redis_queue_service.pop_next_task_queue_entry
            payload = await pop_next(redis_url=redis_url)
            if payload:
                self._redis_queue_cursor = (start_index + offset) % len(redis_urls)
                if not payload.get("redis_url"):
                    payload["redis_url"] = redis_url
                return payload, redis_url
        self._redis_queue_cursor = (self._redis_queue_cursor + 1) % len(redis_urls)
        return None, None

    def _prune_stale_active_tasks(self) -> None:
        stale = [
            task_id
            for task_id in list(self._active_task_ids)
            if task_id not in self._running_futures or self._running_futures[task_id].done()
        ]
        for task_id in stale:
            self._active_task_ids.discard(task_id)
            self._running_futures.pop(task_id, None)

    def _schedule_failed_task_retry(
        self,
        *,
        task_id: str,
        failed_task_run_id: str,
        delay_seconds: int,
        started_by: str | None = None,
        run_input: dict | None = None,
    ) -> None:
        run_at = utc_now() + timedelta(seconds=max(0, int(delay_seconds)))
        identity = {"started_by": started_by, "run_input": run_input} if started_by or run_input else {}
        try:
            self.scheduler.add_job(
                self.run_task_now,
                "date",
                id=f"failed-task-retry:{failed_task_run_id}",
                replace_existing=True,
                run_date=run_at,
                kwargs={"task_id": task_id, "trigger_type": "retry", "trigger_id": failed_task_run_id, "priority": 10,
                        **identity},
            )
        except Exception:
            logger.exception("[scheduler] Failed to schedule retry for task %s (%s)", task_id, failed_task_run_id)

    async def _estimate_queue_wait_seconds(self, db) -> int:
        from sqlalchemy import select

        from ...models import TaskRun

        result = await db.execute(
            select(TaskRun)
            .where(TaskRun.started_at.is_not(None), TaskRun.completed_at.is_not(None))
            .order_by(TaskRun.completed_at.desc())
            .limit(20)
        )
        completed_runs = result.scalars().all()
        durations = [
            max(1, int((run.completed_at - run.started_at).total_seconds()))
            for run in completed_runs
            if run.started_at and run.completed_at
        ]
        if not durations:
            return 60
        return max(5, int(sum(durations) / len(durations)))

    async def _refresh_queue_wait_estimates(self, db) -> None:
        from sqlalchemy import select

        from ...models import TaskQueueEntry, TaskRun

        # Nothing waits (the usual case on every 0.75 s dispatcher tick): there is no estimate to refresh, so neither
        # the duration estimate (a sort over ``task_runs``) nor the running count is read.
        waiting_entries = (
            (
                await db.execute(
                    select(TaskQueueEntry)
                    .join(TaskRun, TaskRun.id == TaskQueueEntry.task_run_id)
                    .where(
                        TaskQueueEntry.started_at.is_(None),
                        TaskQueueEntry.completed_at.is_(None),
                        TaskRun.status == "queued",
                    )
                    .order_by(TaskQueueEntry.priority.desc(), TaskQueueEntry.queued_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if not waiting_entries:
            return
        avg_duration = await self._estimate_queue_wait_seconds(db)
        active_count = (
            (
                await db.execute(
                    select(TaskQueueEntry)
                    .join(TaskRun, TaskRun.id == TaskQueueEntry.task_run_id)
                    .where(
                        TaskQueueEntry.started_at.is_not(None),
                        TaskQueueEntry.completed_at.is_(None),
                        TaskRun.status == "running",
                    )
                )
            )
            .scalars()
            .all()
        )
        offset = len(active_count)
        for index, entry in enumerate(waiting_entries):
            entry.estimated_wait_seconds = max(0, (offset + index) * avg_duration)

    async def _pool_config(self, db, task):
        if not task.project_id:
            raise TaskNotRunnableError(task.id, TASK_WORKSPACE_REQUIRED)
        return await get_or_create_worker_pool_config(db, task.project_id)

    async def _decide_queue_backend(self, pool_config) -> QueueBackendDecision:
        desired_backend = str(pool_config.queue_backend or "database").strip().lower()
        redis_url = str(pool_config.redis_url or "").strip() or None
        is_redis_available = redis_queue_service.is_redis_queue_available
        if desired_backend == "redis" and await is_redis_available(redis_url):
            return QueueBackendDecision(backend="redis", redis_url=redis_url, last_error=None)
        if desired_backend == "redis":
            return QueueBackendDecision(
                backend="database", redis_url=redis_url, last_error="redis queue unavailable; using database queue"
            )
        return QueueBackendDecision(backend="database", redis_url=redis_url, last_error=None)

    async def _insert_task_run(
        self,
        db,
        task,
        *,
        trigger_type: str,
        trigger_id: str | None,
        started_by: str | None,
        priority: int | None,
        decision: QueueBackendDecision,
        run_input: dict | None = None,
    ):
        from ...models import TaskQueueEntry, TaskRun

        try:
            queue_priority = int(priority if priority is not None else (task.config or {}).get("queue_priority") or 5)
        except (TypeError, ValueError):
            queue_priority = 5
        queue_priority = max(1, min(int(queue_priority), 10))

        task_run = TaskRun(
            id=str(uuid.uuid4()),
            task_id=task.id,
            session_id=None,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            status="queued",
            started_by=started_by or task.owner_id,
            # An alert-started run carries the alert beside the Action's config, set before dispatch.
            input_={**(task.config or {}), **run_input} if run_input else task.config or {},
            started_at=None,
        )
        db.add(task_run)
        await db.flush()
        task_run.started_at = None

        queue_entry = TaskQueueEntry(
            task_run_id=task_run.id,
            project_id=task.project_id,
            task_type=str(task.task_type or "scheduled_task"),
            required_domain=infer_required_domain(task),
            status="pending",
            priority=queue_priority,
            source_event_id=trigger_id,
            queued_at=utc_now(),
            max_attempts=max(1, int((task.config or {}).get("max_attempts") or 3)),
            estimated_wait_seconds=0,
            queue_backend="database",
        )
        queue_entry.payload = dict(task.config or {})
        expires_minutes = (task.config or {}).get("queue_expire_minutes")
        if expires_minutes not in (None, ""):
            try:
                queue_entry.expires_at = utc_now() + timedelta(minutes=max(1, int(expires_minutes)))
            except (TypeError, ValueError):
                queue_entry.expires_at = None
        required_worker_id = str((task.config or {}).get("required_worker_id") or "").strip()
        if required_worker_id:
            queue_entry.required_worker_id = required_worker_id
        queue_entry.queue_backend = decision.backend
        if decision.last_error:
            queue_entry.last_error = decision.last_error
        db.add(queue_entry)
        await db.flush()
        return task_run, queue_entry

    async def _push_redis_entry(self, task, task_run, queue_entry, redis_url: str | None) -> None:
        enqueue_entry = redis_queue_service.enqueue_task_queue_entry
        await enqueue_entry(
            entry_id=queue_entry.id,
            project_id=queue_entry.project_id,
            task_run_id=task_run.id,
            task_id=task.id,
            priority=queue_entry.priority,
            queued_at=queue_entry.queued_at,
            required_domain=queue_entry.required_domain,
            required_worker_id=queue_entry.required_worker_id,
            redis_url=redis_url,
        )

    async def _push_redis_entry_after_commit(self, task, task_run, queue_entry, decision: QueueBackendDecision) -> None:
        try:
            await self._push_redis_entry(task, task_run, queue_entry, decision.redis_url)
        except Exception as exc:  # noqa: BLE001 - the committed row stays authoritative
            logger.error(
                "scheduler_redis_push_failed",
                extra={"task_run_id": task_run.id, "error_type": type(exc).__name__},
            )

    @staticmethod
    def _queued_payload(task, task_run, queue_entry) -> dict[str, object]:
        return {
            "status": "queued",
            "task_id": task.id,
            "task_run_id": task_run.id,
            "queue_entry_id": queue_entry.id,
            "priority": queue_entry.priority,
            "estimated_wait_seconds": queue_entry.estimated_wait_seconds,
        }

    async def _enqueue_task_run(
        self,
        task_id: str,
        *,
        trigger_type: str,
        trigger_id: str | None,
        started_by: str | None = None,
        priority: int | None = None,
        allow_inactive: bool = False,
        run_input: dict | None = None,
    ) -> dict[str, object]:
        from sqlalchemy import select

        from ...models import Task

        session_factory = self._get_session_factory()
        async with session_factory() as db:
            task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
            if not task:
                raise TaskNotRunnableError(task_id, TASK_NOT_FOUND)
            if not task.is_active and not allow_inactive:
                raise TaskNotRunnableError(task_id, TASK_INACTIVE)
            pool_config = await self._pool_config(db, task)
            decision = await self._decide_queue_backend(pool_config)
            task_run, queue_entry = await self._insert_task_run(
                db,
                task,
                trigger_type=trigger_type,
                trigger_id=trigger_id,
                started_by=started_by,
                priority=priority,
                decision=decision,
                run_input=run_input,
            )
            if queue_entry.queue_backend == "redis":
                await self._push_redis_entry(task, task_run, queue_entry, decision.redis_url)
            await self._refresh_queue_wait_estimates(db)
            await db.commit()
            return self._queued_payload(task, task_run, queue_entry)

    async def run_task_now(
        self,
        task_id: str,
        trigger_type: str = "manual",
        trigger_id: str | None = None,
        priority: int | None = None,
        started_by: str | None = None,
        allow_inactive: bool = False,
        run_input: dict | None = None,
    ):
        self._prune_stale_active_tasks()
        return await self._enqueue_task_run(
            task_id,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            priority=priority,
            started_by=started_by,
            allow_inactive=allow_inactive,
            run_input=run_input,
        )

    async def claim_queued_run(self, task_run_id: str) -> bool:
        """Claim a queued DB-queue run for execution in this process; ``False`` when a dispatcher has it."""
        from sqlalchemy import update

        from ...models import TaskQueueEntry, TaskRun

        now = utc_now()
        async with self._get_session_factory()() as db:
            claimed = await db.execute(
                update(TaskQueueEntry)
                .where(
                    TaskQueueEntry.task_run_id == task_run_id,
                    TaskQueueEntry.status == "pending",
                    TaskQueueEntry.started_at.is_(None),
                    TaskQueueEntry.completed_at.is_(None),
                )
                .values(
                    status="in_progress",
                    assigned_to=None,
                    assigned_at=now,
                    started_at=now,
                    last_heartbeat=now,
                    attempt_count=func.coalesce(TaskQueueEntry.attempt_count, 0) + 1,
                    last_error=None,
                )
                .execution_options(synchronize_session=False)
            )
            if int(claimed.rowcount or 0) != 1:
                await db.rollback()
                return False
            started = await db.execute(
                update(TaskRun)
                .where(TaskRun.id == task_run_id, TaskRun.status == "queued")
                .values(status="running", started_at=func.coalesce(TaskRun.started_at, now),
                        owner_process_id=current_process_id())
                .execution_options(synchronize_session=False)
            )
            if int(started.rowcount or 0) != 1:
                await db.rollback()
                return False
            await db.commit()
        return True

    def cancel_task(self, task_id: str):
        fut = self._running_futures.pop(task_id, None)
        if fut and not fut.done():
            fut.cancel()
        self._active_task_ids.discard(task_id)
