"""Distributed worker registration and runtime heartbeat loop helpers."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.worker_pool.state import record_capacity_snapshot

from ...models import AgentWorker, DistributedWorkerRegistration
from ...time_utils import utc_now
from ..named_connections.contract import NAMED_CONNECTION_CONNECTORS
from ..named_connections.resolver import serving_connection
from ..project.service import get_project_config

logger = logging.getLogger(__name__)


async def register_distributed_worker(
    db: AsyncSession,
    *,
    worker_id: str,
    backend: str = "database",
    domains: list[str] | None = None,
    capabilities: dict[str, Any] | None = None,
    pod_name: str | None = None,
) -> dict[str, Any]:
    worker = await db.get(AgentWorker, worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    row = (
        await db.execute(
            select(DistributedWorkerRegistration).where(DistributedWorkerRegistration.worker_id == worker_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = DistributedWorkerRegistration(
            id=str(uuid.uuid4()),
            worker_id=worker_id,
            project_id=worker.project_id,
        )
        db.add(row)
    row.backend = str(backend or "database")
    row.status = "ready"
    row.domains = list(domains or [])
    row.capabilities = dict(capabilities or {})
    row.pod_name = pod_name
    row.queue_name = f"project-{worker.project_id}"
    row.last_heartbeat = utc_now()
    row.is_active = 1
    await db.flush()
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "project_id": row.project_id,
        "backend": row.backend,
        "status": row.status,
        "domains": list(row.domains or []),
        "capabilities": dict(row.capabilities or {}),
        "queue_name": row.queue_name,
        "pod_name": row.pod_name,
        "last_heartbeat": row.last_heartbeat.isoformat() if row.last_heartbeat else None,
    }



_DEFAULT_CONNECTOR_KEYS = ("jira_url", "k8s_context", "grafana_url", "prometheus_url", "bitbucket_url", "github_token")


def connectors_verified(config: dict) -> bool:
    """Whether the Workspace's resolved config serves any connector.

    The resolved config, never raw Project.config: a connection comes only from the tool entries, so a
    URL left in Project.config verifies nothing. A Workspace served only by named connections has an empty
    default entry: a usable named connection verifies too.
    """
    return any(bool(config.get(key)) for key in _DEFAULT_CONNECTOR_KEYS) or any(
        serving_connection(config, connector) is not None for connector in NAMED_CONNECTION_CONNECTORS
    )


STOP_SECONDS = 10


class DistributedWorker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], worker_id: str, *, backend: str = "database"):
        self._session_factory = session_factory
        self.worker_id = worker_id
        self.backend = backend
        self._monitor_task: asyncio.Task | None = None
        self._queue_task: asyncio.Task | None = None
        self._running = False
        self._stopping = asyncio.Event()

    async def _pause(self, seconds: float) -> None:
        """Sleep between iterations; returns at once when the worker stops."""
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def _register_in_db(self) -> dict[str, Any]:
        async with self._session_factory() as db:
            worker = await db.get(AgentWorker, self.worker_id)
            if worker is None:
                raise HTTPException(status_code=404, detail="Worker not found")
            payload = await register_distributed_worker(
                db,
                worker_id=self.worker_id,
                backend=self.backend,
                domains=[],
                capabilities={"queue_consumer": True, "monitor_loop": True},
                pod_name=f"worker-{self.worker_id[:8]}",
            )
            await db.commit()
            return payload

    async def _verify_connectors(self) -> None:
        async with self._session_factory() as db:
            registration = (
                await db.execute(
                    select(DistributedWorkerRegistration).where(
                        DistributedWorkerRegistration.worker_id == self.worker_id
                    )
                )
            ).scalar_one_or_none()
            worker = await db.get(AgentWorker, self.worker_id)
            if registration is None or worker is None:
                return
            verified = connectors_verified(await get_project_config(worker.project_id, db))
            capabilities = dict(registration.capabilities or {})
            capabilities["connectors_verified"] = verified
            registration.capabilities = capabilities
            registration.last_heartbeat = utc_now()
            await db.commit()

    async def _load_knowledge(self) -> None:
        async with self._session_factory() as db:
            registration = (
                await db.execute(
                    select(DistributedWorkerRegistration).where(
                        DistributedWorkerRegistration.worker_id == self.worker_id
                    )
                )
            ).scalar_one_or_none()
            worker = await db.get(AgentWorker, self.worker_id)
            if registration is None or worker is None:
                return
            capabilities = dict(registration.capabilities or {})
            # The governed Knowledge is recalled per turn, so there is nothing to load up front.
            capabilities["knowledge_loaded"] = False
            capabilities.pop("project_queue_entries", None)
            registration.capabilities = capabilities
            registration.last_heartbeat = utc_now()
            await db.commit()

    async def _start_monitor_loop(self) -> None:
        self._running = True
        self._stopping.clear()

        async def _runner() -> None:
            while self._running:
                try:
                    async with self._session_factory() as db:
                        registration = (
                            await db.execute(
                                select(DistributedWorkerRegistration).where(
                                    DistributedWorkerRegistration.worker_id == self.worker_id
                                )
                            )
                        ).scalar_one_or_none()
                        if registration:
                            registration.status = "ready"
                            registration.last_heartbeat = utc_now()
                        await record_capacity_snapshot(db, worker_id=self.worker_id)
                        await db.commit()
                except Exception:
                    logger.exception("Worker monitor loop failed", extra={"worker_id": self.worker_id})
                await self._pause(15)

        self._monitor_task = asyncio.create_task(_runner(), name=f"distributed-worker-monitor:{self.worker_id}")

    async def _start_queue_consumer(self) -> None:
        async def _runner() -> None:
            while self._running:
                try:
                    async with self._session_factory() as db:
                        registration = (
                            await db.execute(
                                select(DistributedWorkerRegistration).where(
                                    DistributedWorkerRegistration.worker_id == self.worker_id
                                )
                            )
                        ).scalar_one_or_none()
                        if registration:
                            registration.last_heartbeat = utc_now()
                            registration.status = "ready"
                            await db.commit()
                except Exception:
                    logger.exception("Worker queue consumer heartbeat failed", extra={"worker_id": self.worker_id})
                await self._pause(10)

        self._queue_task = asyncio.create_task(_runner(), name=f"distributed-worker-queue:{self.worker_id}")

    async def start(self) -> dict[str, Any]:
        payload = await self._register_in_db()
        await self._verify_connectors()
        await self._load_knowledge()
        await self._start_monitor_loop()
        await self._start_queue_consumer()
        return payload

    async def stop(self) -> None:
        """Let each loop finish its iteration (never cancelled inside a transaction), then end it.

        A loop cancelled inside its session leaves the SQLite test database locked; the next
        test's teardown then waits 120 s for the writer and fails ("database is locked"). A loop still running after
        STOP_SECONDS is cancelled."""
        self._running = False
        self._stopping.set()
        tasks = [task for task in (self._monitor_task, self._queue_task) if task is not None]
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=STOP_SECONDS)
            for task in pending:
                task.cancel()
            for task in pending:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
