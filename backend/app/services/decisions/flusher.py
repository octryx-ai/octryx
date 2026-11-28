"""Write buffered decisions on a timer and at shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PolicyDecisionCounter
from ..policy_engine.decision_log import flush_decision_log, pending_records
from .recorder import restore_allow_counts, take_allow_counts

logger = logging.getLogger(__name__)
FLUSH_SECONDS = 5.0


async def _write_allow_counts(db: AsyncSession, items: list) -> None:
    for hour, gate, action, workspace_id, count in items:
        row = (await db.execute(select(PolicyDecisionCounter).where(
            PolicyDecisionCounter.hour == hour, PolicyDecisionCounter.gate == gate,
            PolicyDecisionCounter.action == action, PolicyDecisionCounter.workspace_id == workspace_id,
        ))).scalar_one_or_none()
        if row is None:
            db.add(PolicyDecisionCounter(hour=hour, gate=gate, action=action, workspace_id=workspace_id, count=count))
        else:
            row.count = int(row.count or 0) + count
    await db.flush()


async def flush_allow_counts(db: AsyncSession | None = None) -> int:
    items = take_allow_counts()
    if not items:
        return 0
    try:
        if db is not None:
            await _write_allow_counts(db, items)
        else:
            from ...db import core as db_core

            async with db_core.async_session_factory() as session:
                await _write_allow_counts(session, items)
                await session.commit()
    except Exception:
        restore_allow_counts(items)
        raise
    return len(items)


async def flush_decisions() -> None:
    try:
        if pending_records():
            await flush_decision_log()
    except Exception:  # noqa: BLE001 - kept in the buffer for the next flush
        logger.warning("decision_log_flush_failed", exc_info=True)
    try:
        await flush_allow_counts()
    except Exception:  # noqa: BLE001 - kept for the next flush
        logger.warning("decision_counter_flush_failed", exc_info=True)


class DecisionFlusher:
    def __init__(self, interval: float = FLUSH_SECONDS) -> None:
        self.interval = interval
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            await flush_decisions()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="decision-flusher")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await flush_decisions()


decision_flusher = DecisionFlusher()
