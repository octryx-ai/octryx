"""Task Scheduler – loads scheduled tasks from DB and runs them via APScheduler."""

import asyncio
import logging
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .coordination import SchedulerCoordinator
from .dispatch import SchedulerQueueMixin
from .execution import execute_task as _execute_task
from .tickets import (
    find_reusable_task_session as _find_reusable_task_session,
)

logger = logging.getLogger(__name__)


class TaskScheduler(SchedulerQueueMixin):
    """Manages scheduled tasks from the tasks table."""

    def __init__(self, session_factory=None):
        self.scheduler = AsyncIOScheduler()
        self._session_factory = session_factory
        self._loaded_task_ids: set[str] = set()
        self._active_task_ids: set[str] = set()
        self._running_futures: dict[str, asyncio.Task] = {}
        # task id -> the TaskRun this process executes for it; a run cancelled in the database by
        # another process (an API request) is cancelled here by the dispatch loop.
        self._running_task_run_ids: dict[str, str] = {}
        self._queue_dispatch_task: asyncio.Task | None = None
        self._queue_stop_event = asyncio.Event()
        self._max_parallel_queue_tasks = 2
        self._redis_queue_cursor = 0
        # Registration ownership across API and worker processes; started only by start.
        self._coordinator = SchedulerCoordinator(self)

    def set_session_factory(self, session_factory) -> None:
        self._session_factory = session_factory

    def _get_session_factory(self):
        if self._session_factory is not None:
            return self._session_factory
        from .. import db as database_module

        return database_module.async_session_factory

    async def _run_agent_for_task(
        self,
        db,
        task,
        prompt: str,
        *,
        agent_definition=None,
        runtime_target_id=None,
        thinking_level=None,
        session_metadata: dict | None = None,
        on_session_ready=None,
        max_iterations: int | None = None,
        skip_session_reuse: bool = False,
        parent_session_id: str | None = None,
        run_as_user_id: str | None = None,
    ):
        from ..models import Session
        from ..services.run_capability.schedule_capability import schedule_session_capability_metadata

        # The task's declared class governs its agent runs; nothing declared runs read_only.
        session_metadata = {**(session_metadata or {}), **schedule_session_capability_metadata(task)}
        reusable_session = None
        if not skip_session_reuse:
            reusable_session = await _find_reusable_task_session(db, task)
        # An alert-started run executes as the webhook's automation identity, not the owner.
        run_user_id = run_as_user_id or task.owner_id
        if reusable_session is None:
            session = Session(
                id=str(uuid.uuid4()),
                user_id=run_user_id,
                project_id=task.project_id,
                agent_type=(agent_definition.get("agentType") if agent_definition else task.agent_type)
                or task.agent_type,
                status="active",
                origin="scheduler",
                metadata_=session_metadata or {},
                parent_session_id=parent_session_id,
            )
            db.add(session)
            await db.flush()
        else:
            session = reusable_session
            session.agent_type = (
                agent_definition.get("agentType") if agent_definition else task.agent_type
            ) or task.agent_type
            session.status = "active"
            merged_metadata = dict(session.metadata_ or {})
            merged_metadata.update(session_metadata or {})
            session.metadata_ = merged_metadata
            await db.flush()

        if on_session_ready is not None:
            maybe_awaitable = on_session_ready(session)
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable

        from ..services.devices.agent_runtime import run_task_on_pool

        return session, await run_task_on_pool(db, task=task, session=session, prompt=prompt, user_id=run_user_id)

    async def _execute_task(
        self,
        task_id: str,
        trigger_type: str = "manual",
        trigger_id: str | None = None,
        task_run_id: str | None = None,
        assigned_worker_id: str | None = None,
        queue_domain: str | None = None,
    ):
        return await _execute_task(
            scheduler=self,
            task_id=task_id,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            task_run_id=task_run_id,
            assigned_worker_id=assigned_worker_id,
            queue_domain=queue_domain,
        )

    def get_jobs(self) -> list[dict]:
        """List all scheduled jobs."""
        return [
            {
                "id": job.id,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in self.scheduler.get_jobs()
        ]

    def shutdown(self):
        """Shutdown the scheduler."""
        self._queue_stop_event.set()
        self._coordinator.stop_nowait()
        if self._queue_dispatch_task and not self._queue_dispatch_task.done():
            self._queue_dispatch_task.cancel()
        self.scheduler.shutdown(wait=False)
