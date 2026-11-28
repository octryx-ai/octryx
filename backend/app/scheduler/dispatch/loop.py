"""Queue dispatch loop for the task scheduler."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.worker_pool.dispatch import select_dispatch_worker
from app.services.worker_pool.helpers import infer_required_domain
from app.services.worker_pool.state import claim_worker_assignment

from ...models.project.task import WORKFLOW_RUN_BINDING
from ...services.redis_queue import service as redis_queue_service
from ...services.runtime_ownership.process_identity import current_process_id
from ...time_utils import utc_now
from .agent_definition_binding import is_agent_definition_bound

logger = logging.getLogger(__name__)




AGENT_RUN_TASK_TYPE = "agent_run"


async def _can_execute_locally_without_worker(db: Any, task: Any) -> bool:
    from sqlalchemy import select

    from ...models import TaskStep

    if is_agent_definition_bound(task) or getattr(task, "dispatch_binding", None) == WORKFLOW_RUN_BINDING:
        return True
    config = dict(task.config or {})
    if str(config.get("local_execution") or "").strip().lower() == "deterministic":
        return config.get("requires_worker") is False

    steps = (
        (
            await db.execute(
                select(TaskStep)
                .where(TaskStep.task_id == task.id, TaskStep.is_enabled.is_(True))
                .order_by(TaskStep.position.asc())
            )
        )
        .scalars()
        .all()
    )
    if not steps:
        # An agent turn runs on the runner pool, like an agent-bound Action's: no worker profile has to hold it.
        return str(getattr(task, "task_type", "") or "") == AGENT_RUN_TASK_TYPE

    for step in steps:
        step_type = str(step.step_type or "").strip()
        if step_type == "condition":
            continue
        if step_type in {"connector_fetch", "output"} and str(step.connector_action or "").strip():
            continue
        return False
    return True


def _claim_local_scheduler_assignment(queue_entry: Any, task_run: Any) -> None:
    now = utc_now()
    queue_entry.assigned_to = None
    queue_entry.assigned_at = now
    queue_entry.started_at = now
    queue_entry.last_heartbeat = now
    queue_entry.status = "in_progress"
    queue_entry.attempt_count = int(queue_entry.attempt_count or 0) + 1
    queue_entry.last_error = None
    task_run.status = "running"
    task_run.started_at = task_run.started_at or now
    task_run.owner_process_id = current_process_id()


class SchedulerDispatchLoopMixin:
    """Dispatch pending queue entries to available workers."""

    async def _dispatch_queued_runs_once(self) -> int:
        from sqlalchemy import select

        from ...models import Task, TaskQueueEntry, TaskRun

        self._prune_stale_active_tasks()
        available_slots = max(0, self._max_parallel_queue_tasks - len(self._active_task_ids))
        if available_slots <= 0:
            return 0

        session_factory = self._get_session_factory()
        async with session_factory() as db:
            active_task_ids = set(self._active_task_ids)
            selected: list[tuple[Any, Any, Any, Any | None, str]] = []
            deferred_redis_entries: list[dict[str, Any]] = []
            now = utc_now()

            while len(selected) < available_slots:
                redis_payload, redis_url = await self._pop_next_redis_queue_entry(db)
                if not redis_payload:
                    break
                entry_id = str(redis_payload.get("entry_id") or "").strip()
                entry_redis_url = str(redis_payload.get("redis_url") or redis_url or "").strip() or None
                if not entry_id:
                    continue
                row = (
                    await db.execute(
                        select(TaskQueueEntry, TaskRun, Task)
                        .join(TaskRun, TaskRun.id == TaskQueueEntry.task_run_id)
                        .join(Task, Task.id == TaskRun.task_id)
                        .where(TaskQueueEntry.id == entry_id)
                    )
                ).one_or_none()
                if row is None:
                    remove_entry = redis_queue_service.remove_task_queue_entry
                    await remove_entry(entry_id, redis_url=entry_redis_url)
                    continue
                queue_entry, task_run, task = row
                if (
                    queue_entry.queue_backend != "redis"
                    or queue_entry.status != "pending"
                    or task_run.status != "queued"
                ):
                    remove_entry = redis_queue_service.remove_task_queue_entry
                    await remove_entry(entry_id, redis_url=entry_redis_url)
                    continue
                if queue_entry.completed_at is not None or queue_entry.started_at is not None:
                    remove_entry = redis_queue_service.remove_task_queue_entry
                    await remove_entry(entry_id, redis_url=entry_redis_url)
                    continue
                if task_run.task_id in active_task_ids:
                    deferred_redis_entries.append(redis_payload)
                    continue
                if queue_entry.expires_at and queue_entry.expires_at <= now:
                    queue_entry.status = "dead_letter"
                    queue_entry.completed_at = now
                    queue_entry.last_error = "queue entry expired before assignment"
                    task_run.status = "skipped"
                    task_run.error = "queue entry expired before assignment"
                    task_run.completed_at = now
                    remove_entry = redis_queue_service.remove_task_queue_entry
                    await remove_entry(entry_id, redis_url=entry_redis_url)
                    continue
                worker, reason = await select_dispatch_worker(db, task=task, queue_entry=queue_entry)
                if worker is None:
                    if reason == "no_available_workers" and await _can_execute_locally_without_worker(db, task):
                        _claim_local_scheduler_assignment(queue_entry, task_run)
                        remove_entry = redis_queue_service.remove_task_queue_entry
                        await remove_entry(entry_id, redis_url=entry_redis_url)
                        selected.append((queue_entry, task_run, task, None, infer_required_domain(task, queue_entry)))
                        active_task_ids.add(task_run.task_id)
                        continue
                    queue_entry.last_error = reason
                    deferred_redis_entries.append(redis_payload)
                    continue
                await claim_worker_assignment(db, worker=worker, queue_entry=queue_entry, task_run=task_run)
                remove_entry = redis_queue_service.remove_task_queue_entry
                await remove_entry(entry_id, redis_url=entry_redis_url)
                selected.append((queue_entry, task_run, task, worker, infer_required_domain(task, queue_entry)))
                active_task_ids.add(task_run.task_id)

            result = await db.execute(
                select(TaskQueueEntry, TaskRun, Task)
                .join(TaskRun, TaskRun.id == TaskQueueEntry.task_run_id)
                .join(Task, Task.id == TaskRun.task_id)
                .where(
                    TaskQueueEntry.queue_backend != "redis",
                    TaskQueueEntry.started_at.is_(None),
                    TaskQueueEntry.completed_at.is_(None),
                    TaskQueueEntry.status == "pending",
                    TaskRun.status == "queued",
                )
                .order_by(TaskQueueEntry.priority.desc(), TaskQueueEntry.queued_at.asc())
                # An API process may claim a queued run for itself ("run now",
                # ``claim_queued_run``). Locked rows are skipped, and a row claimed meanwhile no longer
                # matches when the lock is granted, so no run is started by both (PostgreSQL; SQLite ignores it).
                .with_for_update(of=TaskQueueEntry, skip_locked=True)
            )
            rows = result.all()
            for queue_entry, task_run, task in rows:
                if len(selected) >= available_slots:
                    break
                if task_run.task_id in active_task_ids:
                    continue
                if queue_entry.expires_at and queue_entry.expires_at <= now:
                    queue_entry.status = "dead_letter"
                    queue_entry.completed_at = now
                    queue_entry.last_error = "queue entry expired before assignment"
                    task_run.status = "skipped"
                    task_run.error = "queue entry expired before assignment"
                    task_run.completed_at = now
                    continue
                worker, reason = await select_dispatch_worker(db, task=task, queue_entry=queue_entry)
                if worker is None:
                    if reason == "no_available_workers" and await _can_execute_locally_without_worker(db, task):
                        _claim_local_scheduler_assignment(queue_entry, task_run)
                        selected.append((queue_entry, task_run, task, None, infer_required_domain(task, queue_entry)))
                        active_task_ids.add(task_run.task_id)
                        continue
                    queue_entry.last_error = reason
                    continue
                await claim_worker_assignment(db, worker=worker, queue_entry=queue_entry, task_run=task_run)
                selected.append((queue_entry, task_run, task, worker, infer_required_domain(task, queue_entry)))
                active_task_ids.add(task_run.task_id)

            deferred_by_url: dict[str, list[dict[str, Any]]] = {}
            for entry in deferred_redis_entries:
                redis_url = str(entry.get("redis_url") or "").strip()
                if redis_url:
                    deferred_by_url.setdefault(redis_url, []).append(entry)
            for redis_url, entries in deferred_by_url.items():
                requeue_entries = redis_queue_service.requeue_task_queue_entries
                await requeue_entries(entries, redis_url=redis_url)
            if not selected:
                await self._refresh_queue_wait_estimates(db)
                await db.commit()
                return 0
            await self._refresh_queue_wait_estimates(db)
            await db.commit()

        for _queue_entry, task_run, _task, worker, required_domain in selected:
            self._spawn_execution(
                self._execute_task(
                    task_run.task_id,
                    trigger_type=task_run.trigger_type or "manual",
                    trigger_id=task_run.trigger_id,
                    task_run_id=task_run.id,
                    assigned_worker_id=worker.id if worker else None,
                    queue_domain=required_domain,
                )
            )
        return len(selected)

    def _spawn_execution(self, coroutine: Any) -> asyncio.Task:
        tasks = self.__dict__.setdefault("_execution_tasks", set())
        task = asyncio.create_task(coroutine)
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    async def _wait_for_dispatched_runs(self) -> None:
        tasks = list(self.__dict__.get("_execution_tasks", ()))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _cancel_runs_cancelled_elsewhere(self) -> list[str]:
        from sqlalchemy import select

        from ...models import TaskRun

        running = dict(getattr(self, "_running_task_run_ids", None) or {})
        if not running:
            return []
        async with self._get_session_factory()() as db:
            cancelled = set(
                (
                    await db.execute(
                        select(TaskRun.id).where(TaskRun.id.in_(sorted(set(running.values()))),
                                                 TaskRun.status == "cancelled")
                    )
                ).scalars()
            )
        stopped: list[str] = []
        for task_id, run_id in running.items():
            if run_id in cancelled and self._running_task_run_ids.get(task_id) == run_id:
                logger.info("[scheduler] Task run %s cancelled elsewhere; cancelling it here", run_id)
                self.cancel_task(task_id)
                stopped.append(task_id)
        return stopped

    async def _queue_dispatch_loop(self) -> None:
        while not self._queue_stop_event.is_set():
            try:
                await self._cancel_runs_cancelled_elsewhere()
            except Exception:
                logger.exception("[scheduler] Cancelled-run check failed")
            try:
                await self._dispatch_queued_runs_once()
            except Exception:
                logger.exception("[scheduler] Task queue dispatch failed")
            try:
                await asyncio.wait_for(self._queue_stop_event.wait(), timeout=0.75)
            except TimeoutError:
                continue
