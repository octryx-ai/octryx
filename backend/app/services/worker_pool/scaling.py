"""Pool scaling decisions and autoscaler runtime."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.worker_pool.state import get_or_create_worker_pool_config, record_capacity_snapshot

from ...models import AgentWorker, Project, TaskQueueEntry
from ...time_utils import ensure_utc, utc_now, utc_now_aware

logger = logging.getLogger(__name__)


async def _project_queue_stats(db: AsyncSession, project_id: str) -> dict[str, int]:
    now = utc_now()
    rows = (
        await db.execute(
            select(TaskQueueEntry.priority, func.count(TaskQueueEntry.id))
            .where(
                TaskQueueEntry.project_id == project_id,
                TaskQueueEntry.status.in_(("pending", "in_progress")),
                (TaskQueueEntry.expires_at.is_(None) | (TaskQueueEntry.expires_at > now)),
            )
            .group_by(TaskQueueEntry.priority)
        )
    ).all()
    depth = sum(int(count or 0) for _, count in rows)
    critical_depth = sum(int(count or 0) for priority, count in rows if int(priority or 0) >= 9)
    low_priority_depth = sum(int(count or 0) for priority, count in rows if int(priority or 0) <= 4)
    return {
        "queue_depth": depth,
        "critical_depth": critical_depth,
        "low_priority_depth": low_priority_depth,
    }


async def evaluate_pool_scaling(db: AsyncSession, *, project_id: str) -> dict[str, Any]:
    config = await get_or_create_worker_pool_config(db, project_id)
    stats = await _project_queue_stats(db, project_id)
    now = utc_now_aware()
    action = "none"
    reason = "steady"

    current_workers = int(config.current_workers or config.min_workers or 1)
    cooldown_up = timedelta(minutes=max(1, int(config.scale_up_cooldown_minutes or 5)))
    cooldown_down = timedelta(minutes=max(1, int(config.scale_down_cooldown_minutes or 15)))

    if stats["critical_depth"] > 0:
        desired = min(
            int(config.max_workers or current_workers),
            max(current_workers, int(config.min_workers or 1) + stats["critical_depth"]),
        )
        last_scale_at = ensure_utc(config.last_scale_at)
        if desired > current_workers and (last_scale_at is None or now - last_scale_at >= cooldown_up):
            config.current_workers = desired
            config.last_scale_action = "up"
            config.last_scale_at = now
            action = "up"
            reason = "critical_queue_depth"
    elif stats["queue_depth"] > int(config.scale_up_threshold or 5):
        last_scale_at = ensure_utc(config.last_scale_at)
        if current_workers < int(config.max_workers or current_workers) and (
            last_scale_at is None or now - last_scale_at >= cooldown_up
        ):
            config.current_workers = min(int(config.max_workers or current_workers), current_workers + 1)
            config.last_scale_action = "up"
            config.last_scale_at = now
            action = "up"
            reason = "queue_depth_above_threshold"
    elif stats["queue_depth"] < int(config.scale_down_threshold or 1):
        last_scale_at = ensure_utc(config.last_scale_at)
        if current_workers > int(config.min_workers or 1) and (
            last_scale_at is None or now - last_scale_at >= cooldown_down
        ):
            config.current_workers = max(int(config.min_workers or 1), current_workers - 1)
            config.last_scale_action = "down"
            config.last_scale_at = now
            action = "down"
            reason = "queue_depth_below_threshold"

    return {
        "project_id": project_id,
        "queue_depth": stats["queue_depth"],
        "critical_depth": stats["critical_depth"],
        "low_priority_depth": stats["low_priority_depth"],
        "current_workers": int(config.current_workers or 0),
        "action": action,
        "reason": reason,
    }


class WorkerPoolAutoscaler:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None
        self._running = False
        self.last_run_at = None

    async def run_once(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        async with self._session_factory() as db:
            rows = (await db.execute(select(Project.id).order_by(Project.created_at.asc()))).all()
            for (project_id,) in rows:
                summary = await evaluate_pool_scaling(db, project_id=project_id)
                summaries.append(summary)
            workers = (await db.execute(select(AgentWorker.id).where(AgentWorker.is_active.is_(True)))).all()
            for (worker_id,) in workers:
                await record_capacity_snapshot(db, worker_id=worker_id)
            await db.commit()
        self.last_run_at = utc_now()
        return summaries

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True

        async def _runner() -> None:
            while self._running:
                try:
                    await self.run_once()
                except Exception:
                    logger.exception("Worker pool autoscaler iteration failed")
                await asyncio.sleep(30)

        self._task = asyncio.create_task(_runner(), name="worker-pool-autoscaler")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
