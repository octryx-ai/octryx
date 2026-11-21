"""Waiting nodes have a reminder and a timeout.

A run that waits for a reply, a confirmation or an external state gets one reminder after
``reminder_hours`` (default 24, an event the run's history and the Inbox show) and pauses after
``timeout_hours`` (defaults: reply and confirmation 72, watch 120) with ``no_reply`` / ``watch_timeout``: the
requester then continues waiting, changes the plan or aborts. An approval's timeout is the platform's pending
approval TTL (``approval/stale_expiry``); its expiry pauses the run (``approval_timeout``).

Publish & prove adds two waiting kinds under the same policy (reminder after 24 h, pause after 72 h unless the node sets
``reminder_hours`` / ``timeout_hours``): ``functional_acceptance`` (a page published with the acceptance pending)
pauses ``acceptance_timeout``, ``audience_receipt`` (the audience principal did not run the check) pauses
``audience_unproven``. Both pauses offer "continue waiting" and the declared exception.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import ensure_utc, utc_now
from ..agent_gateway.presence_devices import expire_presence
from .graph import graph_for_run
from .limits import pause_run
from .records import WorkflowRunError, lock_run, record_event
from .states import (
    PAUSE_ACCEPTANCE_TIMEOUT,
    PAUSE_AUDIENCE_UNPROVEN,
    PAUSE_NO_REPLY,
    PAUSE_WATCH_TIMEOUT,
    STATUS_WAITING,
    WAITING_AUDIENCE_RECEIPT,
    WAITING_CONFIRMATION,
    WAITING_FUNCTIONAL_ACCEPTANCE,
    WAITING_REPLY,
    WAITING_WATCH,
)

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 300
DEFAULT_REMINDER_HOURS = 24
DEFAULT_TIMEOUT_HOURS = {WAITING_REPLY: 72, WAITING_CONFIRMATION: 72, WAITING_WATCH: 120,
                         WAITING_FUNCTIONAL_ACCEPTANCE: 72, WAITING_AUDIENCE_RECEIPT: 72}
_PAUSE_REASON = {
    WAITING_REPLY: PAUSE_NO_REPLY, WAITING_CONFIRMATION: PAUSE_NO_REPLY, WAITING_WATCH: PAUSE_WATCH_TIMEOUT,
    WAITING_FUNCTIONAL_ACCEPTANCE: PAUSE_ACCEPTANCE_TIMEOUT, WAITING_AUDIENCE_RECEIPT: PAUSE_AUDIENCE_UNPROVEN,
}


def _hours(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key)
    return value if type(value) is int and value > 0 else default


async def sweep_waiting_runs(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Remind once, then pause overdue waiting runs; returns how many paused."""
    from .handoff.lifecycle import sweep_handoffs

    await sweep_handoffs(db)
    now = ensure_utc(now or utc_now())
    await resume_after_seat_reset(db, now=now)
    from .device_silence import sweep_device_steps

    await sweep_device_steps(db, now=now)  # a step waiting for a device that stopped answering
    from .deferred_action import sweep_deferred_actions

    await sweep_deferred_actions(db, now=now)  # a repository step whose start was lost or whose executor died
    runs = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.status == STATUS_WAITING, WorkflowRun.waiting_kind.in_(tuple(DEFAULT_TIMEOUT_HOURS))
    ))).scalars().all()
    paused = 0
    for run_id in [run.id for run in runs]:
        run = await db.get(WorkflowRun, run_id)
        if await _due(db, run, now) is None:
            continue  # not due: never claimed, never locked
        # Claim the run and re-read it: a person may have decided it since the query (never pause a moved run).
        try:
            run = await lock_run(db, run)
        except WorkflowRunError:
            continue
        due = await _due(db, run, now)
        if due == "timeout":
            kind, config = str(run.waiting_kind), await _config(db, run)
            await pause_run(db, run, reason=_PAUSE_REASON[kind], actor_id=None, detail={
                "message": f"nothing arrived within {_hours(config, 'timeout_hours', DEFAULT_TIMEOUT_HOURS[kind])} h",
                "resume": {"kind": "waiting", "waiting_kind": kind},
            })
            paused += 1
        elif due == "reminder":
            state = dict(run.node_state or {})
            run.node_state = {**state, "waiting": {**dict(state.get("waiting") or {}), "reminded_at": now.isoformat()}}
            record_event(db, run, "reminder", node_id=run.current_node_id, detail={"waiting_kind": run.waiting_kind})
        await db.commit()  # one run at a time: no claim is held while the next run is looked at
    return paused


EVENT_SEAT_RESET_RESUMED = "seat_reset_resumed"


async def resume_after_seat_reset(db: AsyncSession, *, now: datetime) -> list[str]:
    """Runs paused because the seat was at its limit with no same-class company model
    (``seat_limited_no_same_class_fallback``) go on by themselves once the reset the account named has passed
    (instead of a person resuming it by hand at the reset). An unnamed reset still waits for a
    person. Returns the resumed run ids."""
    from .octryx.seat_fallback import REASON_NO_SAME_CLASS
    from .pause import _resume
    from .states import STATUS_PAUSED

    now = ensure_utc(now)
    resumed: list[str] = []
    runs = (await db.execute(select(WorkflowRun.id).where(WorkflowRun.status == STATUS_PAUSED))).scalars().all()
    for run_id in runs:
        run = await db.get(WorkflowRun, run_id)
        pause = dict(dict(run.node_state or {}).get("pause") or {}) if run is not None else {}
        if pause.get("code") != REASON_NO_SAME_CLASS or pause.get("reset_known") is not True:
            continue
        try:
            reset = ensure_utc(datetime.fromisoformat(str(pause.get("reset_at") or "")))
        except ValueError:
            continue
        if reset > now:
            continue
        try:
            run = await lock_run(db, run)
        except WorkflowRunError:
            continue
        if run.status != STATUS_PAUSED or dict(dict(run.node_state or {}).get("pause") or {}) != pause:
            await db.commit()
            continue  # a person decided it meanwhile
        record_event(db, run, EVENT_SEAT_RESET_RESUMED, node_id=run.current_node_id,
                     detail={"reset_at": pause.get("reset_at"), "engine": pause.get("engine")})
        await _resume(db, run, dict(pause.get("resume") or {"kind": "restart", "node_id": run.current_node_id}),
                      actor_id=run.requested_by)
        await db.commit()
        resumed.append(run.id)
    return resumed


async def _config(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    return node.config if node is not None else {}


async def _due(db: AsyncSession, run: WorkflowRun | None, now: datetime) -> str | None:
    """``timeout`` | ``reminder`` | ``None`` for a waiting run at ``now``."""
    if run is None or run.status != STATUS_WAITING or run.waiting_kind not in DEFAULT_TIMEOUT_HOURS:
        return None
    waiting = dict(dict(run.node_state or {}).get("waiting") or {})
    since = waiting.get("since")
    if not since:
        return None
    config = await _config(db, run)
    waited = now - ensure_utc(datetime.fromisoformat(str(since)))
    kind = str(run.waiting_kind)
    if waited >= timedelta(hours=_hours(config, "timeout_hours", DEFAULT_TIMEOUT_HOURS[kind])):
        return "timeout"
    if not waiting.get("reminded_at") and waited >= timedelta(
            hours=_hours(config, "reminder_hours", DEFAULT_REMINDER_HOURS)):
        return "reminder"
    return None


class WorkflowRunSweepWorker:
    def __init__(self, session_factory, *, interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                async with self._session_factory() as db:
                    await sweep_waiting_runs(db)
            except Exception:
                logger.exception("Workflow run sweep failed")
            try:  # the coordination board's housekeeping rides on the same tick (presence retention)
                async with self._session_factory() as db:
                    await expire_presence(db)
            except Exception:
                logger.exception("Agent presence expiry failed")
            try:  # files fetched from a Mac live a day
                from ..devices.job_files import purge_expired  # noqa: PLC0415

                async with self._session_factory() as db:
                    await purge_expired(db)
            except Exception:
                logger.exception("Device file purge failed")
            try:  # device-sent Codex seat calls whose report never came (``codex_seat_tickets``)
                from ..model_gateway.inbound.codex_seat_tickets import sweep_unreported_tickets  # noqa: PLC0415

                async with self._session_factory() as db:
                    await sweep_unreported_tickets(db)
            except Exception:
                logger.exception("Codex seat ticket sweep failed")
            try:  # full session transcripts live their Workspace's retention
                from ..session_transcripts.retention import purge_expired as purge_transcripts  # noqa: PLC0415

                async with self._session_factory() as db:
                    await purge_transcripts(db)
            except Exception:
                logger.exception("Session transcript purge failed")
            await asyncio.sleep(self._interval_seconds)


__all__ = ["WorkflowRunSweepWorker", "sweep_waiting_runs"]
