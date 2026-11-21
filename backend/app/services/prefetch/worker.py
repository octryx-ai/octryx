"""Background execution worker for tool prefetching.

Turn preparation never reads the prompt to decide which tools run in the background, so nothing
enqueues a job today. The worker and the cache stay as the execution side for an explicit producer (for example a
selected workflow's planned read steps); cache warming must never change what runs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.background_worker_state import (
    record_background_worker_failure,
    record_background_worker_success,
)
from app.tools.context import ToolContext

from ...time_utils import utc_now
from ...tools.registry import execute_tool
from ..run_capability.worker_profiles import worker_tool_context_state
from .cache import (
    build_prefetch_params_hash,
    get_prefetch_cacheability_reason,
    lookup_prefetch_cache,
    store_prefetch_cache_result,
)

logger = logging.getLogger(__name__)


@dataclass
class PrefetchRequest:
    rule_id: str
    tool_name: str
    params: dict[str, Any]
    prefetch_strategy: str


@dataclass
class PrefetchJob:
    session_id: str
    user_id: str
    project_ids: list[str]
    roles: list[str]
    project_config: dict[str, Any]
    workspace_root: str | None
    request_id: str | None
    requests: list[PrefetchRequest]


class PrefetchWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        execute_tool_fn: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._execute_tool = execute_tool_fn or execute_tool
        self._queue: asyncio.Queue[PrefetchJob] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._shutdown = False
        self._pending_keys: set[tuple[str, str, str]] = set()
        self.processed_jobs = 0
        self.completed_prefetches = 0

    def configure(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @property
    def queue_depth(self) -> int:
        return int(self._queue.qsize())

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._shutdown = False
        self._task = asyncio.create_task(self._run_loop(), name="prefetch-worker")

    async def stop(self) -> None:
        self._shutdown = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._pending_keys.clear()

    async def enqueue(self, job: PrefetchJob) -> int:
        enqueued = 0
        for request in job.requests:
            params_hash = build_prefetch_params_hash(request.tool_name, request.params)
            key = (job.session_id, request.tool_name, params_hash)
            if key in self._pending_keys:
                continue
            self._pending_keys.add(key)
            await self._queue.put(
                PrefetchJob(
                    session_id=job.session_id,
                    user_id=job.user_id,
                    project_ids=list(job.project_ids),
                    roles=list(job.roles),
                    project_config=dict(job.project_config or {}),
                    workspace_root=job.workspace_root,
                    request_id=job.request_id,
                    requests=[request],
                )
            )
            enqueued += 1
        return enqueued

    async def run_once(self) -> bool:
        if self._session_factory is None:
            return False
        try:
            job = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return False
        started_at = utc_now()
        try:
            await self._process_job(job)
            await record_background_worker_success(
                self._session_factory,
                worker_name="prefetch_worker",
                owner="prefetch",
                started_at=started_at,
                result={"processed_count": 1, "request_count": len(job.requests), "queue_depth": self.queue_depth},
            )
            return True
        except Exception as exc:
            await record_background_worker_failure(
                self._session_factory,
                worker_name="prefetch_worker",
                owner="prefetch",
                started_at=started_at,
                error=exc,
            )
            raise
        finally:
            self._queue.task_done()
            for request in job.requests:
                params_hash = build_prefetch_params_hash(request.tool_name, request.params)
                self._pending_keys.discard((job.session_id, request.tool_name, params_hash))

    async def _run_loop(self) -> None:
        while not self._shutdown:
            try:
                processed = await self.run_once()
                if not processed:
                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                raise
            except (RuntimeError, ValueError, TypeError, OSError):
                logger.exception("Prefetch worker loop failed")
                await asyncio.sleep(1)

    async def _process_job(self, job: PrefetchJob) -> None:
        if self._session_factory is None:
            return
        self.processed_jobs += 1
        async with self._session_factory() as db:
            tool_context = ToolContext(
                user_id=job.user_id,
                project_ids=list(job.project_ids),
                roles=list(job.roles),
                session_id=job.session_id,
                project_config=dict(job.project_config or {}),
                db=db,
                workspace_root=job.workspace_root,
                request_id=job.request_id,
                run_capability=worker_tool_context_state("prefetch_worker"),
            )
            if any(request.prefetch_strategy == "parallel" for request in job.requests):
                await asyncio.gather(*(self._run_request(db, tool_context, request) for request in job.requests))
            else:
                for request in job.requests:
                    await self._run_request(db, tool_context, request)

    async def _run_request(self, db: AsyncSession, tool_context: ToolContext, request: PrefetchRequest) -> None:
        cacheability_reason = get_prefetch_cacheability_reason(request.tool_name, request.params)
        if cacheability_reason is not None:
            logger.info(
                "Prefetch execution suppressed by governance",
                extra={
                    "session_id": tool_context.session_id,
                    "request_id": tool_context.request_id,
                    "tool_name": request.tool_name,
                    "reason": cacheability_reason,
                },
            )
            return
        cached = await lookup_prefetch_cache(
            db,
            session_id=tool_context.session_id,
            tool_name=request.tool_name,
            params=request.params,
        )
        if cached is not None:
            logger.info(
                "Prefetch execution suppressed by governance",
                extra={
                    "session_id": tool_context.session_id,
                    "request_id": tool_context.request_id,
                    "tool_name": request.tool_name,
                    "reason": "fresh_cache",
                },
            )
            return
        result = await self._execute_tool(request.tool_name, request.params, tool_context)
        row = await store_prefetch_cache_result(
            db,
            session_id=tool_context.session_id,
            tool_name=request.tool_name,
            params=request.params,
            result=result,
        )
        if row is not None:
            self.completed_prefetches += 1


prefetch_worker = PrefetchWorker()

