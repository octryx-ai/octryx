"""Emergency stop: an admin stops all machine work of a Workspace (or the platform) with one audited action.

The device kill switches (``devices/platform_switch``,
``devices/workspace_policy``) stop device turns but leave workflow runs going, so a run dispatches the next item
right after; ``incident_response`` acts on agent chains and task runs only and has no caller. Without this a runaway
loop has to be stopped by hand, run by run.

What it does, only on an explicit request (never an automatic kill):

- every run that works without a person (``running``, or waiting for its device) is **paused** with reason
  ``emergency_stop`` and resume "restart the current node": the run's own Continue picks it up again, nothing is
  lost or aborted. Runs that wait for a person consume nothing and stay as they are;
- every open device job in scope is stopped (``stop_active_jobs``, as the kill switches do);
- **new starts are held**: the scope's safe mode
  (``SafeModeState``, ``block_new_runs``) is switched on, so a webhook Action or a schedule does not
  start new work right after; ``scheduler.execution.task_execution`` skips such a start as ``emergency_stop``. Only
  an explicit :func:`resume_new_starts` by an admin of the scope lifts it;
- one ``kill_switch_logs`` row (action ``pause``, target ``project``/``global``) with the reason, the person and the
  ids; every run gets its ``paused`` event with the same.

The preview lists exactly what a stop would touch, so the page can ask for confirmation with real names.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.devices.job_state import ACTIVE_STATUSES

from ...models import DeviceJob, KillSwitchLog, Project, SafeModeState, User, WorkflowRun
from ...models.runtime.incident_response import (
    ACTION_PAUSE,
    SAFE_MODE_ACTIVE,
    TARGET_GLOBAL,
    TARGET_PROJECT,
)
from ...time_utils import utc_now
from ..devices.jobs import stop_active_jobs
from ..workflow_runs.limits import pause_run
from ..workflow_runs.records import WorkflowRunError, lock_run
from ..workflow_runs.states import STATUS_RUNNING, STATUS_WAITING, WAITING_DEVICE

REASON = "emergency_stop"
MAX_REASON_CHARS = 2000


class EmergencyStopError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _machine_work(workspace_id: str | None):
    query = select(WorkflowRun).where(or_(
        WorkflowRun.status == STATUS_RUNNING,
        (WorkflowRun.status == STATUS_WAITING) & (WorkflowRun.waiting_kind == WAITING_DEVICE)))
    return query.where(WorkflowRun.project_id == workspace_id) if workspace_id else query


def _open_jobs(workspace_id: str | None):
    query = select(DeviceJob).where(DeviceJob.status.in_(ACTIVE_STATUSES))
    return query.where(DeviceJob.workspace_id == workspace_id) if workspace_id else query


async def preview(db: AsyncSession, workspace_id: str | None) -> dict[str, Any]:
    runs = list((await db.execute(_machine_work(workspace_id).order_by(WorkflowRun.updated_at.desc()))).scalars())
    jobs = list((await db.execute(_open_jobs(workspace_id).order_by(DeviceJob.updated_at.desc()))).scalars())
    names = dict((await db.execute(select(Project.id, Project.name).where(
        Project.id.in_({run.project_id for run in runs} | {job.workspace_id for job in jobs if job.workspace_id})
    ))).all()) if runs or jobs else {}
    return {
        "workspace_id": workspace_id,
        "new_starts_held": await new_starts_held(db, workspace_id),
        **await held_by(db, workspace_id),
        "runs": [{"id": run.id, "title": run.title, "workflow_key": run.workflow_key, "status": run.status,
                  "current_node": run.current_node_id,
                  "workspace": {"id": run.project_id, "name": names.get(run.project_id)}} for run in runs],
        "device_jobs": [{"id": job.id, "folder": job.folder, "device_id": job.device_id, "status": job.status,
                         "owner_user_id": job.owner_user_id,
                         "workspace": {"id": job.workspace_id, "name": names.get(job.workspace_id)}}
                        for job in jobs],
    }


async def stop(db: AsyncSession, user: User, workspace_id: str | None, reason: str) -> dict[str, Any]:
    """Pause the machine work and stop the device jobs in scope. Flushes; the caller commits."""
    reason = str(reason or "").strip()
    if not reason:
        raise EmergencyStopError(422, "reason_required", "Say why you stop everything; it goes into the audit log.")
    reason = reason[:MAX_REASON_CHARS]
    who = user.display_name or user.username
    paused: list[str] = []
    for run in list((await db.execute(_machine_work(workspace_id))).scalars()):
        try:
            run = await lock_run(db, run)
        except WorkflowRunError:
            continue  # moved on in between
        if run.status not in (STATUS_RUNNING, STATUS_WAITING):
            continue
        await pause_run(db, run, reason=REASON, actor_id=user.id, detail={
            "message": f"Stopped by {who} (emergency stop): {reason}", "code": REASON, "by": user.id,
            "resume": {"kind": "restart", "node_id": run.current_node_id},
        })
        paused.append(run.id)
    jobs = await stop_active_jobs(db, actor_id=user.id, reason=REASON, workspace_id=workspace_id)
    await _hold_new_starts(db, user, workspace_id, reason)
    log = KillSwitchLog(action=ACTION_PAUSE, target_type=TARGET_PROJECT if workspace_id else TARGET_GLOBAL,
                        target_id=workspace_id, project_id=workspace_id, user_id=user.id, reason=reason,
                        details={"kind": REASON, "paused_runs": paused, "stopped_device_jobs": [j.id for j in jobs]})
    db.add(log)
    await db.flush()
    return {"log_id": log.id, "workspace_id": workspace_id, "paused_runs": paused,
            "stopped_device_jobs": [job.id for job in jobs], "new_starts_held": True}


async def _hold_new_starts(db: AsyncSession, user: User, workspace_id: str | None, reason: str) -> None:
    """Switch the scope's safe mode on (new starts held); a scope already held keeps its first reason."""
    query = select(SafeModeState).where(SafeModeState.project_id == workspace_id)
    state = (await db.execute(query)).scalar_one_or_none()
    if state is not None and state.state == SAFE_MODE_ACTIVE:
        return
    if state is None:
        state = SafeModeState(project_id=workspace_id)
        db.add(state)
    state.state = SAFE_MODE_ACTIVE
    state.reason = reason  # the person's words only; the kill switch log names the kind
    state.activated_by, state.activated_at = user.id, utc_now()
    state.deactivated_by = state.deactivated_at = None
    state.cancel_running_work, state.block_new_runs = False, True


async def held_by(db: AsyncSession, workspace_id: str | None) -> dict[str, Any]:
    """Which stop holds new starts here: ``platform`` wins over ``workspace`` (a Workspace resume cannot lift it).

    ``{"held_by": None, "hold": None}`` when nothing holds; else the scope, who, when and the reason, so the page can
    explain why a Workspace resume answers 409 under a platform stop."""
    scopes = [(None, "platform")] + ([(workspace_id, "workspace")] if workspace_id else [])
    for project_id, scope in scopes:
        state = (await db.execute(select(SafeModeState).where(SafeModeState.project_id == project_id))
                 ).scalar_one_or_none()
        if state is None or state.state != SAFE_MODE_ACTIVE or not state.block_new_runs:
            continue
        by = await db.get(User, state.activated_by) if state.activated_by else None
        return {"held_by": scope, "hold": {
            "scope": scope, "workspace_id": project_id, "reason": state.reason,
            "at": state.activated_at.isoformat() if state.activated_at else None,
            "by": {"id": by.id, "name": by.display_name or by.username} if by else None}}
    return {"held_by": None, "hold": None}


async def new_starts_held(db: AsyncSession, workspace_id: str | None) -> bool:
    """Whether new starts in this scope (or on the whole platform) are held by a stop."""
    from app.services.incident_response.safe_mode import is_blocked_by_safe_mode

    held, _reason = await is_blocked_by_safe_mode(db, project_id=workspace_id)
    return held


async def resume_new_starts(db: AsyncSession, user: User, workspace_id: str | None, reason: str) -> dict[str, Any]:
    """Lift the held starts of exactly this scope (a Workspace stop does not lift a platform stop). Commits.

    Like the stop, a resume says why: the reason goes into the audit log."""
    from app.exceptions.api import ValidationError
    from app.services.incident_response.safe_mode import deactivate_safe_mode

    reason = str(reason or "").strip()
    if not reason:
        raise EmergencyStopError(422, "reason_required",
                                 "Say why new starts may run again; it goes into the audit log.")
    try:
        result = await deactivate_safe_mode(db, user_id=user.id, project_id=workspace_id,
                                            reason=reason[:MAX_REASON_CHARS])
    except ValidationError:
        raise EmergencyStopError(409, "not_stopped", "New starts are not held in this scope.") from None
    return {"workspace_id": workspace_id, "new_starts_held": await new_starts_held(db, workspace_id),
            "log_id": result.get("kill_switch_log_id")}


async def history(db: AsyncSession, workspace_id: str | None, *, limit: int = 50) -> list[dict[str, Any]]:
    query = select(KillSwitchLog, User).outerjoin(User, User.id == KillSwitchLog.user_id).where(
        func.coalesce(KillSwitchLog.details["kind"].as_string(), "") == REASON)
    if workspace_id:
        query = query.where(KillSwitchLog.project_id == workspace_id)
    rows = (await db.execute(query.order_by(KillSwitchLog.created_at.desc()).limit(limit))).all()
    return [{"id": log.id, "at": log.created_at.isoformat() if log.created_at else None, "reason": log.reason,
             "workspace_id": log.project_id,
             "by": {"id": by.id, "name": by.display_name or by.username} if by else None,
             "paused_runs": (log.details or {}).get("paused_runs", []),
             "stopped_device_jobs": (log.details or {}).get("stopped_device_jobs", [])} for log, by in rows]


__all__ = ["REASON", "EmergencyStopError", "history", "held_by", "new_starts_held", "preview", "resume_new_starts",
           "stop"]
