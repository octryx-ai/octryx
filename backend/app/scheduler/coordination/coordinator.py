"""Desired-state reconciliation, fenced acknowledgements and guarded fires.

Runs only inside the process that actually schedules (``TaskScheduler.start``, the platform worker
or a single local process with background workers). API-only processes never start it, so they
never register jobs or take the lease; their reload/remove calls only *request* a reconcile, which
is a no-op there.

* **Ownership.** :mod:`.owner_lease`. Without the lease the process registers no job.
* **Reconcile.** Reads every Scheduler row and every Task with a schedule, derives the desired jobs
  by content fingerprint, leaves unchanged jobs untouched, (re)registers changed ones and removes
  jobs whose row is paused, deleted, unscheduled or no longer valid. Then, in one fenced
  transaction, it upserts what it applied under its epoch and deletes acknowledgements of anything
  no longer registered. A refused fence drops every local job.
* **Guarded fire.** The APScheduler callback. Queue-backend availability (external I/O) is decided
  first, outside any lock. Then one transaction: fence ``FOR SHARE`` → the Scheduler (or Task) row
  ``FOR UPDATE`` → the target Task ``FOR SHARE`` → insert the TaskRun and queue entry → record the
  next run → commit. A pause, edit or delete that commits first makes the waiting fire re-read and
  skip; a fire that locked first commits its run, and the change applies to later fires. Raw Redis
  pushes happen only after commit. A pause or delete stops new schedule enqueues only; nothing
  already queued or running is cancelled. No exactly-once promise: occurrence identity is,
  dispatcher claims.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from ...models import Scheduler, SchedulerJobApplication, Task
from ...services.runtime_ownership.process_identity import current_process_id
from ..dispatch.cron_schedule import build_cron_trigger
from .clock import db_now
from .fingerprint import (
    SCHEDULER_KIND,
    TASK_KIND,
    ScheduleRecord,
    job_key,
    parse_job_key,
    scheduler_fingerprint,
    task_fingerprint,
)
from .owner_lease import (
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_LEASE_TTL,
    acquire_owner_lease,
    admit_owner,
    release_owner_lease,
    renew_owner_lease,
)

logger = logging.getLogger(__name__)

DEFAULT_RECONCILE_SECONDS = 10.0
STATUS_REGISTERED = "registered"
STATUS_INVALID = "invalid_schedule"


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _zone_name(zone: Any) -> str | None:
    if zone is None:
        return None
    return str(getattr(zone, "key", None) or zone)[:80]


class SchedulerCoordinator:
    def __init__(
        self,
        registrar: Any,
        *,
        ttl: timedelta = DEFAULT_LEASE_TTL,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
        reconcile_seconds: float = DEFAULT_RECONCILE_SECONDS,
    ) -> None:
        self._registrar = registrar
        self.ttl = ttl
        self.heartbeat_seconds = heartbeat_seconds
        self.reconcile_seconds = reconcile_seconds
        self.epoch: int | None = None
        self._registered: dict[str, str] = {}
        self._task: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        self._last_renew = 0.0

    # ---- lifecycle -------------------------------------------------------------------------------

    @property
    def is_owner(self) -> bool:
        return self.epoch is not None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def registered_fingerprints(self) -> dict[str, str]:
        return dict(self._registered)

    async def start(self) -> None:
        if self.is_running:
            return
        self._wake = asyncio.Event()
        await self.tick()
        self._task = asyncio.create_task(self._run(), name="scheduler-coordination")

    def request_reconcile(self) -> None:
        """Ask the running loop to reconcile now; a no-op where no loop runs (API-only processes)."""
        if self.is_running and self._wake is not None:
            self._wake.set()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._release()

    def stop_nowait(self) -> None:
        """Synchronous shutdown hook: stop the loop, drop local jobs, release the lease best-effort."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
        epoch = self.epoch
        self._drop_local_jobs()
        if epoch is None:
            return
        try:
            asyncio.get_running_loop().create_task(self._release_epoch(epoch))
        except RuntimeError:
            # No running loop: the lease simply expires after its TTL.
            pass

    async def _release(self) -> None:
        epoch = self.epoch
        self._drop_local_jobs()
        if epoch is not None:
            await self._release_epoch(epoch)

    async def _release_epoch(self, epoch: int) -> None:
        try:
            async with self._sessions()() as db:
                await release_owner_lease(db, process_id=current_process_id(), epoch=epoch)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - an unreleased lease simply expires
            logger.warning("scheduler_owner_release_failed", extra={"error_type": type(exc).__name__})

    def _sessions(self):
        """The registrar's current async session factory (tests and probes may replace it)."""
        return self._registrar._get_session_factory()

    async def _run(self) -> None:
        while True:
            assert self._wake is not None
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.reconcile_seconds)
            except TimeoutError:
                pass
            self._wake.clear()
            await self.tick()

    async def tick(self) -> None:
        """Acquire or renew the lease, then reconcile while owning it. Failures are logged by type only."""
        try:
            if not await self._ensure_ownership():
                return
            await self.reconcile_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the next tick applies the same rule again
            logger.error("scheduler_coordination_tick_failed", extra={"error_type": type(exc).__name__})

    async def _ensure_ownership(self) -> bool:
        sessions = self._sessions()
        if self.epoch is None:
            async with sessions() as db:
                epoch = await acquire_owner_lease(db, process_id=current_process_id(), ttl=self.ttl)
                await db.commit()
            if epoch is None:
                return False
            self.epoch = int(epoch)
            self._last_renew = time.monotonic()
            logger.info("scheduler_owner_acquired", extra={"epoch": self.epoch})
            return True
        if time.monotonic() - self._last_renew >= self.heartbeat_seconds:
            async with sessions() as db:
                renewed = await renew_owner_lease(db, process_id=current_process_id(), epoch=self.epoch, ttl=self.ttl)
                await db.commit()
            if not renewed:
                self._lose("renew_refused")
                return False
            self._last_renew = time.monotonic()
        return True

    def _lose(self, reason: str) -> None:
        logger.warning("scheduler_owner_lost", extra={"reason": reason, "epoch": self.epoch})
        self.epoch = None
        self._drop_local_jobs()

    def _drop_local_jobs(self) -> None:
        for key in list(self._registered):
            self._registrar._unregister_job(key)
        self._registered.clear()

    # ---- reconcile -------------------------------------------------------------------------------

    async def _desired(self) -> tuple[dict[str, ScheduleRecord], dict[str, str]]:
        async with self._sessions()() as db:
            schedulers = (await db.execute(select(Scheduler))).scalars().all()
            tasks = (await db.execute(select(Task).where(Task.schedule.is_not(None)))).scalars().all()
            records = [
                (s.is_active is True, ScheduleRecord(SCHEDULER_KIND, s.id, s.cron_expression or "", s.task_id,
                                                     s.name or "", scheduler_fingerprint(s)))
                for s in schedulers
            ] + [
                (t.is_active is True, ScheduleRecord(TASK_KIND, t.id, t.schedule or "", t.id, t.name or "",
                                                     task_fingerprint(t)))
                for t in tasks
            ]
        desired: dict[str, ScheduleRecord] = {}
        invalid: dict[str, str] = {}
        for active, record in records:
            if not active or not record.expression.strip():
                continue
            try:
                build_cron_trigger(record.expression)
            except ValueError:
                invalid[job_key(record.kind, record.id)] = record.fingerprint
                continue
            desired[job_key(record.kind, record.id)] = record
        return desired, invalid

    async def reconcile_once(self) -> None:
        if self.epoch is None:
            return
        desired, invalid = await self._desired()
        for key, record in desired.items():
            if self._registered.get(key) != record.fingerprint:
                self._registrar._register_job(record)
                # Only a job APScheduler actually holds counts as registered; otherwise retry next pass.
                if self._registrar._get_registered_job(key) is None:
                    self._registered.pop(key, None)
                else:
                    self._registered[key] = record.fingerprint
        for key in list(self._registered):
            if key not in desired:
                self._registrar._unregister_job(key)
                del self._registered[key]
        await self._acknowledge(desired, invalid)

    async def _acknowledge(self, desired: dict[str, ScheduleRecord], invalid: dict[str, str]) -> None:
        epoch = self.epoch
        if epoch is None:
            return
        async with self._sessions()() as db:
            if not await admit_owner(db, process_id=current_process_id(), epoch=epoch):
                await db.rollback()
                self._lose("acknowledgement_refused")
                return
            now = await db_now(db)
            existing = {row.job_key: row for row in (await db.execute(select(SchedulerJobApplication))).scalars()}
            wanted: dict[str, tuple[str, str, datetime | None, str | None]] = {}
            for key, record in desired.items():
                job = self._registrar._get_registered_job(key)
                if job is None or self._registered.get(key) != record.fingerprint:
                    # Not registered (yet): no acknowledgement, so the row reads pending, never applied.
                    continue
                # ``next_run_time`` None means the trigger has no further run; the job itself exists.
                next_run = _naive_utc(getattr(job, "next_run_time", None))
                zone = _zone_name(getattr(getattr(job, "trigger", None), "timezone", None))
                wanted[key] = (record.fingerprint, STATUS_REGISTERED, next_run, zone)
            for key, fingerprint in invalid.items():
                wanted[key] = (fingerprint, STATUS_INVALID, None, None)
            for key, (fingerprint, status, next_run, zone) in wanted.items():
                row = existing.get(key)
                if row is None:
                    db.add(SchedulerJobApplication(job_key=key, owner_epoch=epoch, applied_fingerprint=fingerprint,
                                                   status=status, next_run_at=next_run, timezone=zone, applied_at=now))
                elif (row.owner_epoch, row.applied_fingerprint, row.status, row.next_run_at, row.timezone) != (
                    epoch, fingerprint, status, next_run, zone
                ):
                    row.owner_epoch, row.applied_fingerprint, row.status = epoch, fingerprint, status
                    row.next_run_at, row.timezone, row.applied_at = next_run, zone, now
            stale = [key for key in existing if key not in wanted]
            if stale:
                await db.execute(delete(SchedulerJobApplication).where(SchedulerJobApplication.job_key.in_(stale)))
            await db.commit()

    # ---- guarded fire ----------------------------------------------------------------------------

    async def fire(self, kind: str, fingerprint: str, task_id: str, trigger_type: str, trigger_id: str | None = None):
        """The registered APScheduler callback; returns the queued payload or ``None`` when skipped."""
        object_id = trigger_id if kind == SCHEDULER_KIND else task_id
        key = job_key(kind, str(object_id))
        epoch = self.epoch
        if epoch is None:
            return self._skip(key, "not_owner")
        registrar = self._registrar
        registrar._prune_stale_active_tasks()
        sessions = self._sessions()
        # External queue-backend I/O first, outside any lock (its result is a plain value).
        async with sessions() as db:
            preflight = await db.get(Task, task_id)
            if preflight is None:
                return self._skip(key, "task_missing")
            from ..dispatch.backend import TaskNotRunnableError

            try:
                pool_config = await registrar._pool_config(db, preflight)
            except TaskNotRunnableError as refused:  # an Action without its Workspace: typed, nothing queued
                return self._skip(key, refused.reason)
            await db.commit()
        decision = await registrar._decide_queue_backend(pool_config)

        async with sessions() as db:
            if not await admit_owner(db, process_id=current_process_id(), epoch=epoch):
                await db.rollback()
                self._lose("fire_refused")
                return self._skip(key, "not_owner")
            if kind == SCHEDULER_KIND:
                row = (
                    await db.execute(select(Scheduler).where(Scheduler.id == object_id).with_for_update())
                ).scalar_one_or_none()
                if row is None or row.is_active is not True or scheduler_fingerprint(row) != fingerprint:
                    await db.rollback()
                    self.request_reconcile()
                    return self._skip(key, "schedule_changed")
                task = (
                    await db.execute(select(Task).where(Task.id == row.task_id).with_for_update(read=True))
                ).scalar_one_or_none()
            else:
                task = (
                    await db.execute(select(Task).where(Task.id == object_id).with_for_update())
                ).scalar_one_or_none()
                if task is not None and task_fingerprint(task) != fingerprint:
                    await db.rollback()
                    self.request_reconcile()
                    return self._skip(key, "schedule_changed")
            if task is None or task.is_active is not True:
                await db.rollback()
                return self._skip(key, "task_inactive")
            task_run, queue_entry = await registrar._insert_task_run(
                db, task, trigger_type=trigger_type, trigger_id=trigger_id, started_by=None, priority=None,
                decision=decision,
            )
            await registrar._refresh_queue_wait_estimates(db)
            await self._record_next_run(db, key, epoch)
            payload = registrar._queued_payload(task, task_run, queue_entry)
            await db.commit()
        if queue_entry.queue_backend == "redis":
            await registrar._push_redis_entry_after_commit(task, task_run, queue_entry, decision)
        return payload

    async def _record_next_run(self, db, key: str, epoch: int) -> None:
        """Inside the admitted fire transaction: the job's next run is already the following occurrence."""
        job = self._registrar._get_registered_job(key)
        row = await db.get(SchedulerJobApplication, key)
        if job is None or row is None or row.owner_epoch != epoch:
            return
        row.next_run_at = _naive_utc(job.next_run_time)
        row.applied_at = await db_now(db)

    @staticmethod
    def _skip(key: str, reason: str) -> None:
        kind, object_id = parse_job_key(key)
        logger.info("scheduler_fire_skipped", extra={"kind": kind, "object_id": object_id, "reason": reason})
        return None


__all__ = [
    "DEFAULT_RECONCILE_SECONDS",
    "STATUS_INVALID",
    "STATUS_REGISTERED",
    "SchedulerCoordinator",
]
