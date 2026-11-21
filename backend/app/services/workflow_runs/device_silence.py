"""A step that waits for its device (``pipeline.run``, a hands-on pass, a workspace preparation: a ``waiting`` event
with an ``action`` at the run's current node) pauses ``device_unreachable`` instead of waiting forever.

Without this, a device service that died while the run waited for its pipeline left the run ``running`` at
``pipeline`` for as long as nobody looked, with nothing in the attention list. The sweep
pauses such a run with cause environment and the next step "check or restart the launcher":

- ``device_offline``: the device is not reachable (no channel, no recent tick) for ``device_offline_grace_s``;
- ``device_job_silent``: the device is connected, but nothing arrived for the step for ``device_timeout_s``.

Both are data: the node's ``config`` wins, then the workflow's ``failure_policy``, then the platform default below.
The pause resumes with ``restart`` at the waiting node: the step is offered again, no loop round is spent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...models.runtime.workflow_run import WorkflowRunEvent
from ...time_utils import ensure_utc
from .states import EVENT_NODE_ENTERED, EVENT_WAITING, PAUSE_DEVICE_UNREACHABLE, STATUS_RUNNING

# Platform defaults (a pipeline can take 8 min, a first Flutter web build up to 10; a silent half hour is not work).
DEFAULT_DEVICE_TIMEOUT_S = 1800
DEFAULT_OFFLINE_GRACE_S = 300
CODE_OFFLINE, CODE_SILENT = "device_offline", "device_job_silent"
RECENT_EVENTS = 50


def _seconds(config: dict[str, Any], policy: dict[str, Any], key: str, default: int) -> int:
    for source in (config, policy):
        value = source.get(key)
        if type(value) is int and value > 0:
            return value
    return default


async def _settings(db: AsyncSession, run: WorkflowRun) -> tuple[int, int]:
    """``(device_timeout_s, device_offline_grace_s)`` for the run's current node."""
    from .failure import failure_policy
    from .sweep import _config

    config, policy = await _config(db, run), await failure_policy(db, run) or {}
    return (_seconds(config, policy, "device_timeout_s", DEFAULT_DEVICE_TIMEOUT_S),
            _seconds(config, policy, "device_offline_grace_s", DEFAULT_OFFLINE_GRACE_S))


async def waiting_since_last_event(db: AsyncSession, run: WorkflowRun) -> datetime | None:
    """The time of the run's last event when its current node waits for a device step, else ``None``."""
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id).order_by(
        WorkflowRunEvent.created_at.desc()).limit(RECENT_EVENTS))).scalars().all()
    for event in events:
        if event.node_id != run.current_node_id:
            continue
        if event.kind == EVENT_NODE_ENTERED:
            return None  # the node was entered again after its last wait (or never waited)
        if event.kind == EVENT_WAITING and dict(event.detail or {}).get("action"):
            return ensure_utc(events[0].created_at)
    return None


async def due(db: AsyncSession, run: WorkflowRun, now: datetime) -> tuple[str, int] | None:
    """``(code, silent seconds)`` when the run's waiting device step is overdue, else ``None``."""
    from ...models.security.device import UserDevice
    from ..devices.hub import device_hub
    from .runtime_target.target import stored_target

    target = stored_target(run)
    if run.status != STATUS_RUNNING or not target or target.get("kind") != "device":
        return None
    last = await waiting_since_last_event(db, run)
    if last is None:
        return None
    silent = int((now - last).total_seconds())
    timeout, grace = await _settings(db, run)
    device = await db.get(UserDevice, str(target.get("device_id") or ""))
    if (device is None or not device_hub.reachable(device)) and silent >= grace:
        return CODE_OFFLINE, silent
    if silent >= timeout:
        return CODE_SILENT, silent
    return None


def _message(code: str, silent: int, target: dict[str, Any]) -> str:
    from .run_texts import run_text
    from .runtime_target.target import target_label

    why = ("is not connected" if code == CODE_OFFLINE else "is connected, but the step reported nothing")
    return (f"The device {target_label(target)} {why} for {silent // 60} min while the step waited for it. "
            + run_text("pause.device_unreachable"))


async def pause_unreachable(db: AsyncSession, run: WorkflowRun, code: str, silent: int) -> None:
    from .limits import pause_run
    from .runtime_target.target import stored_target

    target = stored_target(run) or {}
    await pause_run(db, run, reason=PAUSE_DEVICE_UNREACHABLE, actor_id=None, detail={
        "code": code, "silent_s": silent, "device_id": target.get("device_id"),
        "message": _message(code, silent, target),
        "resume": {"kind": "restart", "node_id": run.current_node_id}})


async def sweep_device_steps(db: AsyncSession, *, now: datetime) -> int:
    """Pause every running device run whose waiting step is overdue; returns how many paused."""
    from .records import WorkflowRunError, lock_run

    now = ensure_utc(now)
    ids = (await db.execute(select(WorkflowRun.id).where(WorkflowRun.status == STATUS_RUNNING))).scalars().all()
    paused = 0
    for run_id in ids:
        run = await db.get(WorkflowRun, run_id)
        if run is None or await due(db, run, now) is None:
            continue
        try:
            run = await lock_run(db, run)
        except WorkflowRunError:
            continue
        overdue = await due(db, run, now)  # re-read under the claim: the step may have reported meanwhile
        if overdue is not None:
            await pause_unreachable(db, run, *overdue)
            paused += 1
        await db.commit()
    return paused


__all__ = ["CODE_OFFLINE", "CODE_SILENT", "DEFAULT_DEVICE_TIMEOUT_S", "DEFAULT_OFFLINE_GRACE_S", "due",
           "sweep_device_steps", "waiting_since_last_event"]
