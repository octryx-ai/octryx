"""The runner of manually requested structured builds, beside the projection worker."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ....models.project.knowledge_evidence import PROJECTION_FAILURE_NOT_CONFIGURED
from ....time_utils import utc_now
from ...background_worker_state import record_background_worker_failure, record_background_worker_success
from ..ledger.errors import EvidenceStoreNotConfiguredError
from ..runtime import EvidenceRuntime
from .build import claim_next_build, fail_build, hand_back
from .build_slice import SliceCache, run_build_slice
from .build_states import RESULT_LOST, STATE_COMPLETED, STATE_FAILED, STATE_RUNNING, TRIGGER_MANUAL

logger = logging.getLogger(__name__)

RUNNER_NAME = "structured_build_runner"
SLICE_SECONDS = 2.0
MAX_REVISIONS_PER_SLICE = 25
YIELD_SECONDS = 0.05
MAX_RUN_SECONDS = 600.0
# Run state of an idle runner is written at most this often (a claim's outcome always).
HEALTH_INTERVAL_SECONDS = 60.0
FAILURE_RUNTIME = "runtime_unavailable"
FAILURE_PASS = "runner_pass_failed"
# A runner renews its lease every slice (a few seconds apart); a dead runner's build resumes after this.
LEASE_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0


class StructuredBuildRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        runtime_provider: Callable[[], EvidenceRuntime],
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_run_seconds: float = MAX_RUN_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._runtime_provider = runtime_provider
        self._poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self._max_run_seconds = float(max_run_seconds)
        self.worker_id = f"structured-runner:{os.getpid()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_health: float | None = None
        self._last_failure: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name=RUNNER_NAME)

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        try:
            await task
        finally:
            if self._task is task:
                self._task = None

    async def run_once(self) -> str | None:
        started_at = utc_now()
        try:
            runtime = self._runtime_provider()
        except EvidenceStoreNotConfiguredError:
            # No knowledge store on this platform (a choice, not a fault): idle, as the projection worker reports it.
            await self._health(started_at, failure=PROJECTION_FAILURE_NOT_CONFIGURED)
            return None
        except Exception as error:
            # A configured evidence runtime that fails: the build stays pending and the health shows the failure.
            logger.info("Structured build runner is idle: runtime=%s", type(error).__name__)
            await self._health(started_at, failure=FAILURE_RUNTIME)
            return None
        async with self._session_factory() as db:
            build_id = await claim_next_build(
                db, worker_id=self.worker_id, triggers=(TRIGGER_MANUAL,), lease_seconds=LEASE_SECONDS
            )
        if build_id is None:
            await self._health(started_at, result={"processed_count": 0})
            return None
        deadline = time.monotonic() + self._max_run_seconds
        # Selection and ledger are planned once per claim and followed by the slices, not re-read per slice.
        cache = SliceCache(build_id)
        slices = 0
        while True:
            async with self._session_factory() as db:
                try:
                    slices += 1
                    state = await run_build_slice(
                        db, runtime=runtime, build_id=build_id, worker_id=self.worker_id,
                        budget_seconds=SLICE_SECONDS, max_revisions=MAX_REVISIONS_PER_SLICE,
                        lease_seconds=LEASE_SECONDS, cache=cache,
                    )
                except Exception as error:
                    # The exception type is a fixed token; the message may carry data and is never logged.
                    logger.warning("Structured build slice raised: build=%s error=%s", build_id, type(error).__name__)
                    state = await fail_build(db, build_id, self.worker_id)
                    await self._claim_done(started_at, slices, state)
                    return state
                if state != STATE_RUNNING:
                    # Completed, failed, or lost to another runner: this claim is over, nothing is handed back.
                    await self._claim_done(started_at, slices, state)
                    return state
                if self._stop_event.is_set() or time.monotonic() > deadline:
                    await hand_back(db, build_id, self.worker_id)
                    await self._claim_done(started_at, slices, state)
                    return state
            # Yield between slices: other tasks (requests, the projection worker) run in between.
            await asyncio.sleep(YIELD_SECONDS)

    async def _claim_done(self, started_at, slices: int, state: str) -> None:
        result = {"processed_count": slices, "completed_count": int(state == STATE_COMPLETED),
                  "failed_count": int(state == STATE_FAILED), "handed_back_count": int(state == STATE_RUNNING),
                  "lost_count": int(state == RESULT_LOST)}
        await self._health(started_at, result=result, force=True)

    async def _health(self, started_at, *, result: dict | None = None, failure: str | None = None,
                      force: bool = False) -> None:
        now = time.monotonic()
        if (not force and self._last_health is not None and failure == self._last_failure
                and now - self._last_health < HEALTH_INTERVAL_SECONDS):
            return
        self._last_health, self._last_failure = now, failure
        if failure is not None:
            await record_background_worker_failure(
                self._session_factory, worker_name=RUNNER_NAME, owner=self.worker_id, started_at=started_at,
                error=failure,
            )
        else:
            await record_background_worker_success(
                self._session_factory, worker_name=RUNNER_NAME, owner=self.worker_id, started_at=started_at,
                result=result,
            )

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                state = await self.run_once()
            except Exception:
                # Same contract as the projection worker: never render the error (it may carry endpoints).
                logger.warning("Structured build runner pass ended outside its fixed contract")
                await self._health(utc_now(), failure=FAILURE_PASS, force=True)
                state = None
            if state == STATE_RUNNING:
                continue  # handed back after MAX_RUN_SECONDS: claim it again at once
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue


__all__ = [
    "FAILURE_PASS",
    "FAILURE_RUNTIME",
    "HEALTH_INTERVAL_SECONDS",
    "LEASE_SECONDS",
    "MAX_REVISIONS_PER_SLICE",
    "MAX_RUN_SECONDS",
    "RUNNER_NAME",
    "SLICE_SECONDS",
    "YIELD_SECONDS",
    "StructuredBuildRunner",
]
