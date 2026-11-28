"""Keep this process's lease alive and sweep turns nobody owns (runtime robustness R1)."""

from __future__ import annotations

import asyncio
import logging

from .interrupted_turns import TRIGGER_STARTUP, TRIGGER_SWEEP, InterruptionSettlement, settle_interrupted_turns
from .process_lease import PROCESS_LEASE_HEARTBEAT_SECONDS, release_process_lease, renew_process_lease

logger = logging.getLogger(__name__)

DEFAULT_SWEEP_EVERY_HEARTBEATS = 3


class RuntimeOwnershipWorker:
    def __init__(
        self,
        session_factory,
        *,
        heartbeat_seconds: float = PROCESS_LEASE_HEARTBEAT_SECONDS,
        sweep_every: int = DEFAULT_SWEEP_EVERY_HEARTBEATS,
    ) -> None:
        self._session_factory = session_factory
        self._heartbeat_seconds = heartbeat_seconds
        self._sweep_every = max(1, int(sweep_every))
        self._task: asyncio.Task | None = None

    async def start(self) -> InterruptionSettlement | None:
        if self._task is not None:
            return None
        await self.renew()
        settlement = await self.sweep(trigger=TRIGGER_STARTUP)
        self._task = asyncio.create_task(self._run(), name="runtime-ownership-worker")
        return settlement

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        try:
            async with self._session_factory() as db:
                await release_process_lease(db)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - an unreleased lease simply expires
            logger.warning("runtime_ownership_release_failed", extra={"error_type": type(exc).__name__})

    def is_running(self) -> bool:
        return bool(self._task and not self._task.done())

    async def renew(self) -> None:
        async with self._session_factory() as db:
            await renew_process_lease(db)
            await db.commit()

    async def sweep(self, *, trigger: str = TRIGGER_SWEEP) -> InterruptionSettlement | None:
        try:
            async with self._session_factory() as db:
                settlement = await settle_interrupted_turns(db, trigger=trigger)
                await db.commit()
            return settlement
        except Exception as exc:  # noqa: BLE001 - the next sweep applies the same rule again
            logger.error("runtime_ownership_sweep_failed", extra={"trigger": trigger, "error_type": type(exc).__name__})
            return None

    async def _run(self) -> None:
        beats = 0
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            try:
                await self.renew()
            except Exception as exc:  # noqa: BLE001 - retried on the next heartbeat
                logger.error("runtime_ownership_renew_failed", extra={"error_type": type(exc).__name__})
            beats += 1
            if beats % self._sweep_every == 0:
                await self.sweep()


__all__ = ["DEFAULT_SWEEP_EVERY_HEARTBEATS", "RuntimeOwnershipWorker"]
