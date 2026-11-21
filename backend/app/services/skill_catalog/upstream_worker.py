"""The scheduled upstream check: wakes hourly, checks the sources due by ``update_check_hours``."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...time_utils import utc_now
from ..background_worker_state import record_background_worker_failure, record_background_worker_success
from .upstream import run_scheduled_checks

WORKER_NAME = "skill_upstream_worker"
logger = logging.getLogger(__name__)


class SkillUpstreamWorker:
    def __init__(self, session_factory, interval_seconds: int = 3600) -> None:
        self._session_factory = session_factory
        self._interval_seconds = max(60, int(interval_seconds))
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="skill-upstream-worker")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def is_running(self) -> bool:
        return bool(self._running and self._task and not self._task.done())

    async def run_once(self) -> dict[str, Any]:
        started_at = utc_now()
        try:
            async with self._session_factory() as db:
                result = await run_scheduled_checks(db)
            await record_background_worker_success(self._session_factory, worker_name=WORKER_NAME,
                                                   owner="skill_catalog", started_at=started_at, result=result)
            return result
        except Exception as exc:
            await record_background_worker_failure(self._session_factory, worker_name=WORKER_NAME,
                                                   owner="skill_catalog", started_at=started_at, error=exc)
            raise

    async def _run(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Skill upstream worker failed")
            await asyncio.sleep(self._interval_seconds)


__all__ = ["SkillUpstreamWorker"]
