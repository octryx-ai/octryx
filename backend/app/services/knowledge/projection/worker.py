"""Managed consumer of durable Knowledge projection obligations.

The worker owns only lifecycle and polling. Claim fencing, lease renewal, retry,
dead-letter and schema activation remain inside :class:`EvidenceProjector` and
the outbox modules. Shutdown is deliberately non-cancelling: setting the stop
event prevents the next claim, while the active projector turn is allowed to
commit its fenced transition and close its database session.

The worker runs one slice of a due source-sync structured-graph build per tick; manually requested
builds run in the structured build runner, whose lifecycle this worker owns.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.knowledge.structured.build_states import COOPERATIVE_TRIGGERS

from ....models.project.knowledge_evidence import PROJECTION_FAILURE_NOT_CONFIGURED
from ....time_utils import utc_now
from ...background_worker_state import record_background_worker_failure, record_background_worker_success
from ..ledger.errors import EvidenceLedgerContractError, EvidenceStoreNotConfiguredError
from ..runtime import EvidenceRuntime, get_evidence_runtime
from ..structured.build import run_next_build
from ..structured.build_runner import StructuredBuildRunner
from .failures import failure_token
from .outbox_lease import MAX_CLAIMED_BY_CHARS
from .projector import EvidenceProjector
from .projector_outcome import ProjectionOutcome

logger = logging.getLogger(__name__)

MAX_ENTRIES_PER_TICK = 8
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
WORKER_NAME = "knowledge_projection_worker"


class KnowledgeProjectionWorker:
    """Poll and drain a fixed number of due projection entries per tick."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        runtime_provider: Callable[[], EvidenceRuntime] = get_evidence_runtime,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        worker_id: str | None = None,
    ) -> None:
        if worker_id is not None and (
            type(worker_id) is not str or not 0 < len(worker_id) <= MAX_CLAIMED_BY_CHARS
        ):
            raise EvidenceLedgerContractError()
        self._session_factory = session_factory
        self._runtime_provider = runtime_provider
        self._poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self._worker_id_override = worker_id
        self._generated_worker_id: str | None = None
        self._generated_process_id: int | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._build_runner = StructuredBuildRunner(session_factory, runtime_provider=runtime_provider)

    @property
    def worker_id(self) -> str:
        if self._worker_id_override is not None:
            return self._worker_id_override
        process_id = os.getpid()
        if self._generated_worker_id is None or self._generated_process_id != process_id:
            self._generated_worker_id = f"projection:{process_id}:{uuid.uuid4().hex}"
            self._generated_process_id = process_id
        return self._generated_worker_id

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name=WORKER_NAME)
        await self._build_runner.start()

    async def stop(self) -> None:
        self._stop_event.set()
        await self._build_runner.stop()
        task = self._task
        if task is None:
            return
        try:
            await task
        finally:
            if self._task is task:
                self._task = None

    async def run_tick(self) -> int:
        """Drain at most one fixed batch and persist only safe aggregate state."""
        started_at = utc_now()
        try:
            runtime = self._runtime_provider()
        except EvidenceStoreNotConfiguredError:
            await self._record_failure(started_at, PROJECTION_FAILURE_NOT_CONFIGURED)
            logger.info("Knowledge projection worker is idle: failure=%s", PROJECTION_FAILURE_NOT_CONFIGURED)
            return 0
        except Exception as error:
            token = failure_token(error)
            await self._record_failure(started_at, token)
            logger.warning("Knowledge projection worker runtime failed: failure=%s", token)
            return 0

        projector = EvidenceProjector(runtime)
        outcomes: list[ProjectionOutcome] = []
        try:
            for _ in range(MAX_ENTRIES_PER_TICK):
                if self._stop_event.is_set():
                    break
                async with self._session_factory() as db:
                    outcome = await projector.project_once(db, worker_id=self.worker_id)
                if outcome is None:
                    break
                outcomes.append(outcome)
        except Exception as error:
            token = failure_token(error)
            await self._record_failure(started_at, token)
            logger.warning("Knowledge projection worker tick failed: failure=%s", token)
            return len(outcomes)
        if not self._stop_event.is_set():
            # One bounded slice of a due source-sync structured-graph build; rule-based, no model call.
            try:
                await run_next_build(
                    self._session_factory, runtime=runtime, worker_id=self.worker_id, triggers=COOPERATIVE_TRIGGERS
                )
            except Exception as error:
                logger.warning("Structured knowledge graph slice failed: failure=%s", failure_token(error))

        await record_background_worker_success(
            self._session_factory,
            worker_name=WORKER_NAME,
            owner=self.worker_id,
            started_at=started_at,
            result={
                "processed_count": len(outcomes),
                "applied_count": sum(outcome.applied for outcome in outcomes),
                "failed_count": sum(outcome.failure is not None for outcome in outcomes),
                "deferred_count": sum(outcome.deferred for outcome in outcomes),
            },
        )
        return len(outcomes)

    async def _record_failure(self, started_at: datetime, token: str) -> None:
        # The background-state helper also accepts arbitrary exceptions. This
        # boundary intentionally passes only the closed projection taxonomy.
        await record_background_worker_failure(
            self._session_factory,
            worker_name=WORKER_NAME,
            owner=self.worker_id,
            started_at=started_at,
            error=token,
        )

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_tick()
            except Exception:
                # A run-state persistence failure must not kill the managed
                # task permanently. The exception itself is deliberately not
                # rendered: database and transport errors can contain endpoint
                # or credential-bearing details, while the next bounded tick
                # provides the recovery path.
                logger.warning("Knowledge projection worker tick ended outside its fixed contract")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue
