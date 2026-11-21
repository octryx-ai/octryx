"""A run whose device cannot take its turn now waits ``waiting_for_device`` and goes on when the device can.

When a device run's turn cannot start because the device is offline, paused or at its parallel-job limit
(``octryx.continuation``: the refusal of ``devices.chat_turn.start_device_turn``), the run does not fail and does
not run anywhere else: it waits with a card that names the device, the folder and what to do (start the device, or
switch the run's runtime). The pending continuation stays; once the device's channel ticks again and the device can
take a job (connected, not paused), :func:`resume_for_device` sets the run running and starts that same turn — the
launcher prepares the folder first when the run is at ``workspace.prepare``. Nothing retries a turn by itself while
the device cannot take it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import utc_now
from ..records import record_event
from ..states import EVENT_RESUMED, EVENT_WAITING, STATUS_RUNNING, STATUS_WAITING, WAITING_DEVICE
from .target import stored_target, target_label

# A phase turn that failed on a temporary model service error waits briefly, then runs once more by itself
# (``octryx.continuation``; otherwise "API Error: 503 no available server" paused a run for a person).
REASON_MODEL_RETRY = "model_service_retry"
# A phase turn the launcher refused because it could not reach the platform is offered once more after the same wait.
REASON_PLATFORM_RETRY = "platform_retry"
# The device refusals a run waits out (anything else is a configuration problem the continuation records).
# folder_busy: another run took the folder while this one only watched its pull request (``folder_lock``).
REASON_FOLDER_BUSY = "folder_busy"
WAITABLE_REASONS = frozenset({"device_offline", "device_paused", "device_busy", REASON_MODEL_RETRY,
                              REASON_PLATFORM_RETRY, REASON_FOLDER_BUSY})
_WHY = {
    "device_offline": "is offline",
    "device_paused": "is paused",
    "device_busy": "already runs as many jobs as it allows",
    REASON_MODEL_RETRY: "got a temporary error from the model service",
    REASON_PLATFORM_RETRY: "could not reach the platform to start the turn",
    REASON_FOLDER_BUSY: "has the run's folder in use by another run",
}
_WHAT_TO_DO = {
    "device_offline": "Start it (octryx-claude device start) — the run continues by itself once it connects",
    "device_paused": "Resume it in My settings → Devices or on the device — the run continues by itself",
    "device_busy": "The run continues by itself when one of its jobs finishes",
    REASON_MODEL_RETRY: "The phase runs once more by itself in about a minute",
    REASON_PLATFORM_RETRY: "The turn is offered once more by itself in about a minute",
    REASON_FOLDER_BUSY: "The run continues by itself once that run ends or only watches its pull request",
}


def waiting_question(target: dict[str, Any] | None, reason: str) -> str:
    return (f"Waiting for the device {target_label(target)}: it {_WHY.get(reason, 'cannot take the turn')}. "
            f"{_WHAT_TO_DO.get(reason, 'The run continues by itself once it can')}, or switch the run's runtime.")


def wait_for_device(db: AsyncSession, run: WorkflowRun, *, node_id: str, reason: str,
                    thread_target: dict[str, Any] | None = None, retry_after: str | None = None) -> None:
    """Hold the running run at ``node_id`` until the device can take the turn (one event per reason).
    ``thread_target``: the thread's device target, for a run started without a runtime target. ``retry_after``
    (ISO time): the device's channel resumes the run no earlier than that."""
    target = stored_target(run) or {**dict(thread_target or {}), "kind": "device"}
    state = dict(run.node_state or {})
    previous = dict(state.get("waiting") or {})
    run.status, run.waiting_kind = STATUS_WAITING, WAITING_DEVICE
    run.node_state = {**state, "waiting": {
        "kind": WAITING_DEVICE, "title": "Waiting for the device", "reason": reason,
        "device_id": (target or {}).get("device_id"), "question": waiting_question(target, reason),
        "since": previous.get("since") or utc_now().isoformat(),
        **({"retry_after": retry_after} if retry_after else {})}}
    if previous.get("kind") != WAITING_DEVICE or previous.get("reason") != reason:
        record_event(db, run, EVENT_WAITING, node_id=node_id,
                     detail={"waiting_kind": WAITING_DEVICE, "reason": reason,
                             "device_id": (target or {}).get("device_id")})


# A refusal that waiting cannot fix (configuration, policy): the run waits with the reason and what to do, and is not
# resumed by the device's channel (``resume_for_device`` only resumes ``WAITABLE_REASONS``); changing where the run
# executes (``runtime_target.switch``) continues it.
_REFUSED_WHAT_TO_DO = {
    "content_requires_governed": "The conversation contains sensitive data: choose the governed profile for this "
                                 "device under 'Change where the run executes'",
    "device_runs_disabled": "Device runs are switched off for this Workspace: an admin switches them on, or choose "
                            "Server under 'Change where the run executes'",
    "device_profile_not_allowed": "This profile is not allowed in the Workspace: choose another profile or Server",
    "folder_not_allowlisted": "Allow the folder on the device (octryx-claude device folders add <folder>), or "
                              "choose another folder",
}


def wait_refused(db: AsyncSession, run: WorkflowRun, *, node_id: str, reason: str,
                 thread_target: dict[str, Any] | None = None) -> None:
    """Hold the run visibly when its device turn is refused for a reason waiting cannot fix."""
    target = stored_target(run) or {**dict(thread_target or {}), "kind": "device"}
    state = dict(run.node_state or {})
    what = _REFUSED_WHAT_TO_DO.get(reason, "Choose another place under 'Change where the run executes'")
    run.status, run.waiting_kind = STATUS_WAITING, WAITING_DEVICE
    run.node_state = {**state, "waiting": {
        "kind": WAITING_DEVICE, "title": "The device cannot take this step", "reason": reason, "refused": True,
        "device_id": (target or {}).get("device_id"),
        "question": f"{target_label(target)} cannot take this step ({reason.replace('_', ' ')}). {what}.",
        "since": utc_now().isoformat()}}
    record_event(db, run, EVENT_WAITING, node_id=node_id,
                 detail={"waiting_kind": WAITING_DEVICE, "reason": reason, "refused": True,
                         "device_id": (target or {}).get("device_id")})


def leave_waiting(db: AsyncSession, run: WorkflowRun, *, cause: str) -> None:
    state = dict(run.node_state or {})
    state.pop("waiting", None)
    run.status, run.waiting_kind, run.node_state = STATUS_RUNNING, None, state
    record_event(db, run, EVENT_RESUMED, node_id=run.current_node_id, detail={"from": WAITING_DEVICE, "cause": cause})


def _not_yet(retry_after: Any) -> bool:
    from datetime import datetime

    try:
        return bool(retry_after) and datetime.fromisoformat(str(retry_after)) > utc_now()
    except ValueError:
        return False


async def resume_for_device(db: AsyncSession, device_id: str) -> list[str]:
    """The device can take jobs again: every run waiting for it continues its pending turn; the run ids resumed."""
    from ....models.security.device import DEFAULT_MAX_PARALLEL_JOBS, UserDevice
    from ...devices.hub import device_hub
    from ...devices.jobs import counted_job_count
    from ..octryx.continuation import continue_on_device
    from ..records import lock_run

    device = await db.get(UserDevice, device_id)
    if device is None or device.paused or not device_hub.reachable(device):
        return []
    if await counted_job_count(db, device_id) >= int(device.max_parallel_jobs or DEFAULT_MAX_PARALLEL_JOBS):
        return []
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.status == STATUS_WAITING, WorkflowRun.waiting_kind == WAITING_DEVICE))).scalars().all()
    resumed: list[str] = []
    for run in rows:
        waiting = dict(dict(run.node_state or {}).get("waiting") or {})
        if waiting.get("device_id") != device_id or waiting.get("refused"):
            continue  # a refused turn is not fixed by the device coming online: the person changes the runtime
        if _not_yet(waiting.get("retry_after")):
            continue  # a retry after a temporary model service error waits its short backoff first
        run = await lock_run(db, run)
        if run.status != STATUS_WAITING or run.waiting_kind != WAITING_DEVICE:
            continue
        leave_waiting(db, run, cause="device_available")
        await continue_on_device(db, run)  # refused again: it waits again
        resumed.append(run.id)
    return resumed


__all__ = ["REASON_FOLDER_BUSY", "REASON_MODEL_RETRY", "REASON_PLATFORM_RETRY", "WAITABLE_REASONS", "leave_waiting",
           "resume_for_device", "wait_for_device", "wait_refused", "waiting_question"]
