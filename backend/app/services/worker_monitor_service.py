from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.services.worker_monitor.actions import (
    _apply_monitor_action as _apply_monitor_action_impl,
)
from app.services.worker_monitor.actions import (
    _create_monitor_session as _create_monitor_session_impl,
)
from app.services.worker_monitor.actions import (
    _run_monitor_agent_session as _run_monitor_agent_session_impl,
)
from app.services.worker_monitor.evaluation import (
    evaluate_worker_monitor as _evaluate_worker_monitor_impl,
)

from ..models import AgentWorker, WorkerMonitor
from ..time_utils import ensure_utc, utc_now

logger = logging.getLogger(__name__)

# Kept as a module variable so tests can monkeypatch
# `worker_monitor_service._run_monitor_agent_session`.
_run_monitor_agent_session = _run_monitor_agent_session_impl


async def _create_monitor_session(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker: AgentWorker,
    monitor: WorkerMonitor,
    severity: str,
    detected_value: str,
    action: str,
) -> str | None:
    return await _create_monitor_session_impl(
        db,
        session_factory,
        worker=worker,
        monitor=monitor,
        severity=severity,
        detected_value=detected_value,
        action=action,
        run_monitor_agent_session=_run_monitor_agent_session,
    )


async def _apply_monitor_action(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker: AgentWorker,
    monitor: WorkerMonitor,
    severity: str,
    detected_value: str,
    action: str | None,
) -> tuple[str | None, str | None]:
    return await _apply_monitor_action_impl(
        db,
        session_factory,
        worker=worker,
        monitor=monitor,
        severity=severity,
        detected_value=detected_value,
        action=action,
        run_monitor_agent_session=_run_monitor_agent_session,
    )


async def evaluate_worker_monitor(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker: AgentWorker,
    monitor: WorkerMonitor,
) -> dict[str, Any]:
    return await _evaluate_worker_monitor_impl(
        db,
        session_factory,
        worker=worker,
        monitor=monitor,
        apply_monitor_action=_apply_monitor_action,
    )


async def process_due_worker_monitors(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    counters: dict[str, int] = defaultdict(int)
    async with session_factory() as db:
        now = utc_now()
        workers = (
            (
                await db.execute(
                    select(AgentWorker)
                    .options(selectinload(AgentWorker.runtime_state), selectinload(AgentWorker.onboarding))
                    .where(AgentWorker.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
        for worker in workers:
            monitors = (
                (
                    await db.execute(
                        select(WorkerMonitor)
                        .where(WorkerMonitor.worker_id == worker.id, WorkerMonitor.is_active.is_(True))
                        .order_by(WorkerMonitor.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            for monitor in monitors:
                last_check = ensure_utc(monitor.last_check_at)
                if last_check is not None and last_check > now - timedelta(
                    minutes=int(monitor.check_interval_minutes or 15)
                ):
                    continue
                result = await evaluate_worker_monitor(db, session_factory, worker=worker, monitor=monitor)
                counters["checked"] += 1
                counters[f"severity_{result['severity']}"] += 1
                if result["event"] is not None:
                    counters["events_created"] += 1
        await db.commit()
    return dict(counters)


class WorkerMonitorWorker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], poll_interval_seconds: int = 2):
        self._session_factory = session_factory
        self._poll_interval_seconds = max(1, int(poll_interval_seconds))
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._last_run_stats: dict[str, int] = {}

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
        self._task = None

    async def run_once(self) -> dict[str, int]:
        stats = await process_due_worker_monitors(self._session_factory)
        self._last_run_stats = stats
        return stats

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Worker monitor loop failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue


__all__ = ["evaluate_worker_monitor", "process_due_worker_monitors", "WorkerMonitorWorker"]
