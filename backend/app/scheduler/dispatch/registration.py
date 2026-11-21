"""Scheduler registration and session lifecycle mixin."""

from __future__ import annotations

import logging
from functools import partial

from ...services.clarification_service import expire_overdue_clarification_questions
from ...services.resume_checkpoint_service import find_all_recoverable_sessions
from ...services.session.run_timeout import timeout_stalled_sessions
from ...services.sub_agent_group.service import (
    SUB_AGENT_GROUP_STATUS_TIMED_OUT,
    _reconcile_group_progress,
)
from ...services.worker_pool.task_queue_recovery_service import recover_stale_task_queue_entries
from ...time_utils import utc_now
from ..coordination.fingerprint import (
    SCHEDULER_KIND,
    TASK_KIND,
    ScheduleRecord,
    apscheduler_job_id,
    parse_job_key,
)
from ..tickets.helpers import build_task_session_title, collect_session_tree
from .cron_schedule import build_cron_trigger

logger = logging.getLogger(__name__)


class SchedulerRegistrationMixin:
    """Startup, APScheduler registration, and session tree cleanup.

    Jobs are registered only by the owner of the scheduler lease through the coordinator's
    reconciliation. A change to a task or scheduler row calls ``request_reconcile``, which is a no-op
    in processes that do not schedule (API-only).
    """

    async def _task_run_owns_session(self, db, task_run) -> bool:
        from ...models import Session as AgentSession

        session_id = str(task_run.session_id or "").strip()
        if not session_id:
            return False
        session = await db.get(AgentSession, session_id)
        if session is None:
            return False
        metadata = dict(session.metadata_ or {})
        owner_task_run_id = str(metadata.get("task_run_id") or "").strip()
        if not owner_task_run_id:
            return True
        return owner_task_run_id == task_run.id

    async def _mark_stale_running_runs(self, db):
        from ...services.runtime_ownership.task_runs import orphaned_running_task_runs

        # A run whose executing process is still live (another pod during a RollingUpdate overlap) is not stale.
        stale_runs = await orphaned_running_task_runs(db, include_unowned=True)
        if not stale_runs:
            return
        for task_run in stale_runs:
            task_run.status = "error"
            task_run.error = "Marked stale after scheduler startup"
            task_run.completed_at = utc_now()
        await db.commit()
        for task_run in stale_runs:
            if await self._task_run_owns_session(db, task_run):
                await self._finalize_task_session_tree(
                    db,
                    task_run.session_id,
                    status="error",
                    stop_reason="task_failed",
                )
        logger.warning("[scheduler] Marked %d stale running task runs after startup", len(stale_runs))

    async def _recover_interrupted_runs(self, db):
        """Recover sessions with active checkpoints that were interrupted.

        Finds sessions with run_status=in_progress and an active ContextCheckpoint.
        For auto_retry policy: schedules a recovery turn.
        For manual_resume policy: leaves them for explicit user-triggered resume.
        """
        try:
            from ...services.runtime_ownership.process_lease import live_process_ids

            recoverable = await find_all_recoverable_sessions(db, limit=100)
            # A session whose turn another live process runs (a RollingUpdate overlap) is not interrupted.
            live = await live_process_ids(db, (session.turn_owner_process_id for session, _ in recoverable))
            recoverable = [(session, checkpoint) for session, checkpoint in recoverable
                           if session.turn_owner_process_id not in live]
            if not recoverable:
                return
            recovered_count = 0
            manual_count = 0
            for session, checkpoint in recoverable:
                from ...models.runtime.durable_runtime import RECOVERY_POLICY_AUTO_RETRY

                policy = str(session.recovery_policy or RECOVERY_POLICY_AUTO_RETRY).strip().lower()
                if policy == RECOVERY_POLICY_AUTO_RETRY:
                    # Schedule recovery: clear in_progress so next turn can resume
                    session.run_status = None
                    recovered_count += 1
                else:
                    # manual_resume: keep in_progress so admin/user can explicitly resume
                    manual_count += 1
            await db.commit()
            logger.info(
                "[scheduler] Found %d recoverable sessions (auto: %d, manual: %d)",
                len(recoverable),
                recovered_count,
                manual_count,
            )
        except Exception:
            logger.exception("[scheduler] Error during run recovery scan")

    async def _reconcile_sub_agent_groups(self, db):
        """Recover orphaned SubAgentGroup children after a worker restart.

        Finds SubAgentGroup records with status=running where children are still
        in status=running past the group timeout. Marks timed-out children as
        timed_out and triggers parent session resume.
        """
        try:
            from sqlalchemy import select

            from ...models import SubAgentGroup

            result = await db.execute(
                select(SubAgentGroup).where(SubAgentGroup.status == SUB_AGENT_GROUP_STATUS_TIMED_OUT)
            )
            stale_groups = result.scalars().all()
            for group in stale_groups:
                all_done = await _reconcile_group_progress(db, group)
                if all_done:
                    group.status = SUB_AGENT_GROUP_STATUS_TIMED_OUT  # already timed out
            await db.commit()
            logger.info("[scheduler] Reconciled %d stale sub-agent groups", len(stale_groups))
        except Exception:
            logger.exception("[scheduler] Error during sub-agent group reconciliation")

    async def _recover_stale_task_queue_entries(self, db):
        """Recover task queue entries with stale heartbeats after worker crash.

        Finds entries in status=in_progress where assigned_to is set but the
        worker's heartbeat has gone stale. Resets them to pending for re-dispatch.
        """
        try:
            count = await recover_stale_task_queue_entries(db)
            if count:
                logger.info("[scheduler] Recovered %d stale task queue entries", count)
        except Exception:
            logger.exception("[scheduler] Error during stale task queue entry recovery")

    async def _expire_overdue_clarifications(self, db):
        """Expire open clarification questions past their expires_at deadline."""
        try:
            count = await expire_overdue_clarification_questions(db)
            if count:
                logger.info("[scheduler] Expired %d overdue clarification questions", count)
        except Exception:
            logger.exception("[scheduler] Error during clarification expiration")

    async def _timeout_stalled_sessions(self, db):
        """Timeout sessions stuck in in_progress beyond the allowed duration."""
        try:
            count = await timeout_stalled_sessions(db, timeout_minutes=60)
            if count:
                logger.info("[scheduler] Timed out %d stalled sessions", count)
        except Exception:
            logger.exception("[scheduler] Error during stalled session timeout")

    async def start(self):
        session_factory = self._get_session_factory()
        self.scheduler.start()
        await self._ensure_queue_dispatcher_running()
        await self._sync_redis_queue_backend()

        async with session_factory() as db:
            await self._mark_stale_running_runs(db)
            await self._recover_interrupted_runs(db)
            await self._reconcile_sub_agent_groups(db)
            await self._recover_stale_task_queue_entries(db)
            await self._expire_overdue_clarifications(db)
            await self._timeout_stalled_sessions(db)

        coordinator = self._schedule_coordinator()
        if coordinator is not None:
            # Registration follows the stored rows through the owner lease.
            await coordinator.start()

        logger.info("[scheduler] Started with %d scheduled tasks", len(self._loaded_task_ids))

    # ---- coordination seams ---------------------------------------------------------

    def _schedule_coordinator(self):
        return getattr(self, "_coordinator", None)

    def request_reconcile(self) -> None:
        coordinator = self._schedule_coordinator()
        if coordinator is not None:
            coordinator.request_reconcile()

    def _register_job(self, record: ScheduleRecord) -> None:
        """Register (or replace) one schedule's job with the guarded fire callback."""
        try:
            trigger = build_cron_trigger(record.expression)
        except ValueError:
            logger.error("[scheduler] Invalid cron expression for %s %s", record.kind, record.id)
            return
        fire = partial(self._fire_scheduled, record.kind, record.fingerprint)
        if record.kind == TASK_KIND:
            self.scheduler.add_job(
                fire,
                trigger=trigger,
                id=apscheduler_job_id(TASK_KIND, record.id),
                args=[record.id, "schedule"],
                replace_existing=True,
                max_instances=1,
            )
            self._loaded_task_ids.add(record.id)
            logger.info("[scheduler] Scheduled task %s (%s) with cron: %s", record.id, record.name, record.expression)
            return
        self.scheduler.add_job(
            fire,
            trigger=trigger,
            id=apscheduler_job_id(SCHEDULER_KIND, record.id),
            args=[record.task_id, "scheduler", record.id],
            kwargs={},
            replace_existing=True,
            max_instances=1,
        )
        self._loaded_task_ids.add(record.task_id)
        logger.info(
            "[scheduler] Scheduled scheduler %s → task %s cron: %s", record.id, record.task_id, record.expression
        )

    def _unregister_job(self, key: str) -> None:
        kind, object_id = parse_job_key(key)
        try:
            self.scheduler.remove_job(apscheduler_job_id(kind, object_id))
        except Exception:
            pass
        if kind == TASK_KIND:
            self._loaded_task_ids.discard(object_id)

    def _get_registered_job(self, key: str):
        kind, object_id = parse_job_key(key)
        return self.scheduler.get_job(apscheduler_job_id(kind, object_id))

    async def _fire_scheduled(
        self, kind: str, fingerprint: str, task_id: str, trigger_type: str, trigger_id: str | None = None
    ):
        coordinator = self._schedule_coordinator()
        if coordinator is None:
            return await self.run_task_now(task_id, trigger_type, trigger_id)
        return await coordinator.fire(kind, fingerprint, task_id, trigger_type, trigger_id)

    async def _assign_task_run_session(self, db, task_run, session_id: str):
        from ...models import Session as AgentSession

        task_run.session_id = session_id
        session = await db.get(AgentSession, session_id)
        if session:
            metadata = dict(session.metadata_ or {})
            metadata["task_run_id"] = task_run.id
            metadata["title"] = build_task_session_title(metadata.get("task_name") or "Task run", task_run.id)
            session.metadata_ = metadata
        await db.commit()

    async def _finalize_task_session_tree(
        self, db, root_session_id: str | None, *, status: str, stop_reason: str | None = None,
        preserve_phase_root: bool = False
    ):
        if not root_session_id:
            return
        sessions = await collect_session_tree(db, root_session_id)
        if not sessions:
            return
        ended_at = utc_now()
        for session in sessions:
            if preserve_phase_root and session.id == root_session_id:
                continue  # shared phase-turn settlement owns this root, including any newer plain turn
            session.status = status
            session.ended_at = ended_at
            metadata = dict(session.metadata_ or {})
            if stop_reason:
                metadata["last_stop_reason"] = stop_reason
            session.metadata_ = metadata
        await db.commit()
