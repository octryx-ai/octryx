"""The periodic pull request refresh: one bounded pass over the due rows per tick. The tick runs every minute; an open
PR is due only once per ``REFRESH_INTERVAL``, so host calls do not multiply."""

from __future__ import annotations

import asyncio
import logging

from .refresh import SWEEP_BATCH, sweep_pull_requests

logger = logging.getLogger(__name__)

TICK_SECONDS = 60


class PullRequestRefreshWorker:
    def __init__(self, session_factory, *, interval_seconds: int = TICK_SECONDS, batch: int = SWEEP_BATCH) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._batch = batch
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self) -> dict[str, int]:
        async with self._session_factory() as db:
            return await sweep_pull_requests(db, batch=self._batch)

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            try:
                await self.run_once()
            except Exception:
                logger.exception("Pull request refresh sweep failed")


__all__ = ["PullRequestRefreshWorker", "TICK_SECONDS"]
