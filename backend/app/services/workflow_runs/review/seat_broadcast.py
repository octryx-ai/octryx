"""A seat review offered to several people at once: the first device that takes it reviews."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ....models import DeviceJob, Session, WorkflowRun
from ..records import record_event

EVENT_BROADCAST = "review_seat_broadcast"
# How long a phase's offers wait for a device to take one. A reachable launcher accepts within a channel tick or two;
# this only bounds the wait for a phase whose devices all went quiet, before the next phase is asked.
ACCEPT_SECONDS = 90.0
POLL_SECONDS = 2.0
_TAKEN = frozenset({"accepted", "done"})


async def _wait_a_moment(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


class BroadcastSeatReviewModel:
    runtime_shared = False

    def __init__(self, db: AsyncSession, run: WorkflowRun, phases: list[list[Any]], *,
                 sleep: Callable[[float], Awaitable[Any]] | None = None, clock: Callable[[], float] = time.monotonic,
                 accept_seconds: float = ACCEPT_SECONDS) -> None:
        self._db, self._run, self._phases = db, run, [phase for phase in phases if phase]
        self._sleep, self._clock, self._accept = sleep or _wait_a_moment, clock, accept_seconds
        self._winner: Any = None

    async def answer(self, *, system: str, user: str, images: list[Any] | None = None) -> Any:
        from .seat import SeatReviewUnavailableError

        if self._winner is not None:
            return await self._winner.answer(system=system, user=user, images=images)
        for index, phase in enumerate(self._phases):
            offered = []
            for seat in phase:
                with contextlib.suppress(SeatReviewUnavailableError):
                    offered.append((seat, *await seat.start(system=system, user=user, images=images)))
            taken = await self._first_taken(offered)
            self._record(index, offered, taken)
            if taken is not None:
                self._winner = taken[0]
                return await taken[0].finish(taken[1], taken[2])
        raise SeatReviewUnavailableError("seat_nobody_accepted")

    async def _first_taken(self, offered: list[tuple[Any, DeviceJob, Session]]
                           ) -> tuple[Any, DeviceJob, Session] | None:
        if not offered:
            return None
        deadline = self._clock() + self._accept
        while True:
            for item in offered:
                await self._db.refresh(item[1])
                if item[1].turn_state in _TAKEN:
                    await self._withdraw([other for other in offered if other is not item])
                    return item
            if self._clock() >= deadline:
                await self._withdraw(offered)
                return None
            await self._sleep(POLL_SECONDS)

    async def _withdraw(self, offers: list[tuple[Any, DeviceJob, Session]]) -> None:
        from app.services.devices.job_state import DeviceJobError

        from ...devices.jobs import request_stop
        from .seat import REQUEST_KEY

        for _seat, job, thread in offers:
            with contextlib.suppress(DeviceJobError):  # already finished or rejected: nothing to stop
                await request_stop(self._db, job, actor_id=job.owner_user_id)
            metadata = dict(thread.metadata_ or {})
            metadata.pop(REQUEST_KEY, None)
            thread.metadata_ = metadata
            flag_modified(thread, "metadata_")
        await self._db.commit()

    def _record(self, phase: int, offered: list[tuple[Any, DeviceJob, Session]],
                taken: tuple[Any, DeviceJob, Session] | None) -> None:
        record_event(self._db, self._run, EVENT_BROADCAST, node_id=self._run.current_node_id, detail={
            "phase": phase, "offered_to": [job.owner_user_id for _seat, job, _thread in offered],
            "taken_by": taken[1].owner_user_id if taken is not None else None,
            "device_id": taken[1].device_id if taken is not None else None})


__all__ = ["ACCEPT_SECONDS", "EVENT_BROADCAST", "BroadcastSeatReviewModel"]
