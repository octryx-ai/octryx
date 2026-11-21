"""Background worker that sends due outbound webhook deliveries."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...time_utils import utc_now
from ..background_worker_state import (
    record_background_worker_failure,
    record_background_worker_success,
)
from .delivery import process_outbound_webhook_delivery_batch

logger = logging.getLogger(__name__)


class OutboundWebhookWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_interval_seconds: float = 2.0,
    ):
        self._session_factory = session_factory
        self._poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_once(self) -> int:
        started_at = utc_now()
        try:
            async with self._session_factory() as db:
                processed = await process_outbound_webhook_delivery_batch(db)
            await record_background_worker_success(
                self._session_factory,
                worker_name="outbound_webhook_worker",
                owner="webhooks",
                started_at=started_at,
                result={"processed_count": processed},
            )
            return processed
        except Exception as exc:
            await record_background_worker_failure(
                self._session_factory,
                worker_name="outbound_webhook_worker",
                owner="webhooks",
                started_at=started_at,
                error=exc,
            )
            raise

    async def _run_loop(self) -> None:
        while True:
            try:
                processed = await self.run_once()
                await asyncio.sleep(0.2 if processed else self._poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Outbound webhook worker run failed")
                await asyncio.sleep(self._poll_interval_seconds)
