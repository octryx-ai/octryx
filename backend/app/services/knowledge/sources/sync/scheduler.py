"""Scheduled Source Sync runs: off by default, bounded per tick, never overlapping."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .....models import User
from .....models.project.knowledge_source_sync import CONNECTOR_STATE_ACTIVE, KnowledgeSourceConnector
from .....time_utils import utc_now
from ....background_worker_state import record_background_worker_failure, record_background_worker_success
from ...access.authorization import WorkspaceWriteForbiddenError, authorize_workspace
from ...ledger.errors import EvidenceLedgerError, EvidenceStoreNotConfiguredError
from ...runtime import EvidenceRuntime, get_evidence_runtime
from .incremental import TRIGGER_SCHEDULED
from .runner import SyncRefusedError
from .service_run import run_connector

logger = logging.getLogger(__name__)

WORKER_NAME = "knowledge_source_sync_scheduler"
MAX_CONNECTORS_PER_TICK = 2
DEFAULT_POLL_INTERVAL_SECONDS = 60.0
REASON_SCHEDULE_OWNER_NOT_AUTHORIZED = "schedule_owner_not_authorized"
REASON_EVIDENCE_NOT_CONFIGURED = "evidence_store_not_configured"
REASON_SCHEDULED_RUN_FAILED = "scheduled_run_failed"


async def claim_due_connector(db: AsyncSession, now: datetime) -> str | None:
    due = or_(KnowledgeSourceConnector.next_scheduled_at.is_(None), KnowledgeSourceConnector.next_scheduled_at <= now)
    candidates = (
        await db.execute(
            select(KnowledgeSourceConnector.id, KnowledgeSourceConnector.schedule_interval_minutes)
            .where(
                KnowledgeSourceConnector.schedule_enabled.is_(True),
                KnowledgeSourceConnector.state == CONNECTOR_STATE_ACTIVE,
                due,
            )
            .order_by(KnowledgeSourceConnector.next_scheduled_at, KnowledgeSourceConnector.id)
            .limit(MAX_CONNECTORS_PER_TICK)
        )
    ).all()
    for connector_id, interval in candidates:
        claimed = await db.execute(
            update(KnowledgeSourceConnector)
            .where(
                KnowledgeSourceConnector.id == connector_id, KnowledgeSourceConnector.schedule_enabled.is_(True), due
            )
            .values(next_scheduled_at=now + timedelta(minutes=int(interval)))
        )
        await db.commit()
        if claimed.rowcount == 1:
            return connector_id
    return None


async def run_scheduled_connector(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    connector_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    row = await db.get(KnowledgeSourceConnector, connector_id)
    if row is None or not row.schedule_enabled:
        return REASON_SCHEDULE_OWNER_NOT_AUTHORIZED
    owner = await db.get(User, row.schedule_owner_id) if row.schedule_owner_id else None
    if owner is None or owner.is_active is False:
        return REASON_SCHEDULE_OWNER_NOT_AUTHORIZED
    try:
        authorized = await authorize_workspace(db, current_user=owner, workspace_id=row.project_id, require_author=True)
    except (WorkspaceWriteForbiddenError, EvidenceLedgerError):
        return REASON_SCHEDULE_OWNER_NOT_AUTHORIZED
    try:
        run = await run_connector(
            db,
            runtime=runtime,
            authorized=authorized,
            row=row,
            actor_id=owner.id,
            transport=transport,
            trigger=TRIGGER_SCHEDULED,
        )
    except SyncRefusedError as error:
        return error.reason
    return run.state


def instance_scheduler_enabled() -> bool:
    # With the worker split the api process has its workers off, so only the instance switch decides.
    from .....runtime_toggles import knowledge_source_sync_scheduler_enabled

    return knowledge_source_sync_scheduler_enabled()


class KnowledgeSourceSyncScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        runtime_provider: Callable[[], EvidenceRuntime] = get_evidence_runtime,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        clock: Callable[[], datetime] = utc_now,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._runtime_provider = runtime_provider
        self._poll_interval_seconds = max(1.0, float(poll_interval_seconds))
        self._clock = clock
        # Tests only: a fake source system. Production always talks to the configured instance.
        self._transport = transport
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name=WORKER_NAME)

    async def stop(self) -> None:
        # Non-cancelling, like the projection worker: the active run finishes and frees its lease.
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        try:
            await task
        finally:
            if self._task is task:
                self._task = None

    async def run_tick(self) -> dict[str, int]:
        started_at = utc_now()
        try:
            runtime = self._runtime_provider()
        except EvidenceStoreNotConfiguredError:
            logger.info("Knowledge source sync scheduler is idle: reason=%s", REASON_EVIDENCE_NOT_CONFIGURED)
            await self._record_failure(started_at, REASON_EVIDENCE_NOT_CONFIGURED)
            return {}
        outcomes: dict[str, int] = {}
        for _ in range(MAX_CONNECTORS_PER_TICK):
            if self._stop_event.is_set():
                break
            async with self._session_factory() as db:
                connector_id = await claim_due_connector(db, self._clock())
                if connector_id is None:
                    break
                try:
                    outcome = await run_scheduled_connector(
                        db, runtime=runtime, connector_id=connector_id, transport=self._transport
                    )
                except Exception:
                    # Not rendered: database and transport errors can carry endpoints or credentials.
                    outcome = REASON_SCHEDULED_RUN_FAILED
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            logger.info("Knowledge source sync scheduled run: outcome=%s", outcome)
        await record_background_worker_success(
            self._session_factory,
            worker_name=WORKER_NAME,
            owner=WORKER_NAME,
            started_at=started_at,
            result={"runs": sum(outcomes.values()), **outcomes},
        )
        return outcomes

    async def _record_failure(self, started_at: datetime, token: str) -> None:
        await record_background_worker_failure(
            self._session_factory, worker_name=WORKER_NAME, owner=WORKER_NAME, started_at=started_at, error=token
        )

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_tick()
            except Exception:
                logger.warning("Knowledge source sync scheduler tick ended outside its fixed contract")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue


__all__ = [
    "MAX_CONNECTORS_PER_TICK",
    "REASON_SCHEDULE_OWNER_NOT_AUTHORIZED",
    "KnowledgeSourceSyncScheduler",
    "claim_due_connector",
    "instance_scheduler_enabled",
    "run_scheduled_connector",
]
