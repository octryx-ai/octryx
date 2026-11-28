"""The review bot's hourly pull request sync as a background worker (like ``review.runner.ReviewWorker``)."""

from __future__ import annotations

import asyncio
import logging

from .sync import sync_all

logger = logging.getLogger(__name__)
SYNC_INTERVAL_SECONDS = 3600


class PrReviewSyncWorker:
    def __init__(self, session_factory, *, interval_seconds: int = SYNC_INTERVAL_SECONDS) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
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

    async def _run_loop(self) -> None:
        from .comment_poll import POLL_INTERVAL_SECONDS, poll_all
        from .instant import TICK_SECONDS, Cursor, start_due

        cursor = Cursor()
        synced = polled = float(self._interval_seconds)  # the first pass syncs at once
        while True:
            try:
                async with self._session_factory() as db:
                    totals = await start_due(db, cursor)  # Octryx's own pull requests at once (``instant``)
                    if synced >= self._interval_seconds:
                        synced = polled = 0
                        totals = {**totals, **await sync_all(db)}  # heads and comments
                    elif polled >= POLL_INTERVAL_SECONDS:
                        polled = 0
                        totals = {**totals, **await poll_all(db)}  # ``@octryx`` comments in between
                if totals:
                    logger.info("pr_review_bot.sync_pass %s", totals)
            except Exception:  # noqa: BLE001 - the loop survives a failed pass; the next one retries
                logger.exception("PR review bot sync failed")
            step = min(TICK_SECONDS, POLL_INTERVAL_SECONDS, self._interval_seconds)
            await asyncio.sleep(step)
            synced += step
            polled += step


__all__ = ["SYNC_INTERVAL_SECONDS", "PrReviewSyncWorker"]
