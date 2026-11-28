"""Emergency stop: an admin stops all machine work of a Workspace (or the platform) with one audited action,
only on an explicit request; the preview lists exactly what a stop would touch."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.devices.job_state import BUSY_STATUSES

from ...db import core as db_core
from ...models import DeviceJob, KillSwitchLog, Project, SafeModeState, User, WorkflowRun
from ...models.runtime.incident_response import (
    ACTION_PAUSE,
    SAFE_MODE_ACTIVE,
    TARGET_GLOBAL,
    TARGET_PROJECT,
)
from ...time_utils import utc_now
from ..data_access import platform_maintenance
from ..devices.jobs import stop_active_jobs
from ..project.private_workspace import outside_foreign_private
from ..workflow_runs.limits import pause_run
from ..workflow_runs.records import WorkflowRunError, lock_run
from ..workflow_runs.states import STATUS_RUNNING, STATUS_WAITING, WAITING_DEVICE

REASON = "emergency_stop"
MAINTENANCE_STOP = "emergency stop: stop the device jobs of every Workspace in scope"
MAX_REASON_CHARS = 2000


class EmergencyStopError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# Runs that wait for a person consume nothing and stay as they are.
def _machine_work(workspace_id: str | None):
    query = select(WorkflowRun).where(or_(
        WorkflowRun.status == STATUS_RUNNING,
        (WorkflowRun.status == STATUS_WAITING) & (WorkflowRun.waiting_kind == WAITING_DEVICE)))
    return query.where(WorkflowRun.project_id == workspace_id) if workspace_id else query


def _open_jobs(workspace_id: str | None):
    query = select(DeviceJob).where(DeviceJob.status.in_(BUSY_STATUSES))
    return query.where(DeviceJob.workspace_id == workspace_id) if workspace_id else query


async def preview(db: AsyncSession, workspace_id: str | None, *, viewer_id: str) -> dict[str, Any]:
    runs = list((await db.execute(_machine_work(workspace_id).where(outside_foreign_private(
        WorkflowRun.project_id, viewer_id)).order_by(WorkflowRun.updated_at.desc()))).scalars())
    jobs = list((await db.execute(_open_jobs(workspace_id).where(outside_foreign_private(
        DeviceJob.workspace_id, viewer_id)).order_by(DeviceJob.updated_at.desc()))).scalars())
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
    reason = str(reason or "").strip()
    if not reason:
        raise EmergencyStopError(422, "reason_required", "Say why you stop everything; it goes into the audit log.")
    reason = reason[:MAX_REASON_CHARS]
    who = user.display_name or user.username
    job_ids = await _stop_device_jobs(user, workspace_id)
    # The device kill switches stop device turns only; an unpaused run would dispatch its next item right
    # after. A restart-node resume keeps the run's own Continue working, so nothing is lost or aborted.
    paused: list[str] = []
    visible_work = _machine_work(workspace_id).where(outside_foreign_private(WorkflowRun.project_id, user.id))
    for run in list((await db.execute(visible_work)).scalars()):
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
    # Without the hold a webhook Action or a schedule starts new work right after; task_execution skips such
    # a start as emergency_stop until an admin of the scope calls resume_new_starts.
    await _hold_new_starts(db, user, workspace_id, reason)
    log = KillSwitchLog(action=ACTION_PAUSE, target_type=TARGET_PROJECT if workspace_id else TARGET_GLOBAL,
                        target_id=workspace_id, project_id=workspace_id, user_id=user.id, reason=reason,
                        details={"kind": REASON, "paused_runs": paused, "stopped_device_jobs": job_ids})
    db.add(log)
    await db.flush()
    visible_jobs = await _visible_ids(db, DeviceJob, DeviceJob.workspace_id, job_ids, user.id)
    return {"log_id": log.id, "workspace_id": workspace_id, "paused_runs": paused,
            **_shown(job_ids, visible_jobs, "stopped_device_jobs", "hidden_device_jobs_stopped"),
            "new_starts_held": True}


async def _stop_device_jobs(user: User, workspace_id: str | None) -> list[str]:
    # For safety a platform stop also stops the jobs of other people's private Workspaces; answers only count them.
    # In a session of its own, committed first: its rows never reach the request's session.
    async with platform_maintenance(MAINTENANCE_STOP), db_core.async_session_factory() as own:
        jobs = await stop_active_jobs(own, actor_id=user.id, reason=REASON, workspace_id=workspace_id)
        job_ids = [job.id for job in jobs]
        await own.commit()
    return job_ids


async def _visible_ids(db: AsyncSession, model: Any, workspace: Any, ids: list[str], viewer_id: str) -> set[str]:
    # Only rows that still exist and lie outside other people's private Workspaces; an unresolved id stays hidden.
    if not ids:
        return set()
    return set((await db.execute(select(model.id).where(
        model.id.in_(ids), outside_foreign_private(workspace, viewer_id)))).scalars())


def _shown(ids: list[str], visible: set[str], key: str, hidden_key: str) -> dict[str, Any]:
    return {key: [item for item in ids if item in visible], hidden_key: sum(item not in visible for item in ids)}


async def _hold_new_starts(db: AsyncSession, user: User, workspace_id: str | None, reason: str) -> None:
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
    from app.services.incident_response.safe_mode import is_blocked_by_safe_mode

    held, _reason = await is_blocked_by_safe_mode(db, project_id=workspace_id)
    return held


async def resume_new_starts(db: AsyncSession, user: User, workspace_id: str | None, reason: str) -> dict[str, Any]:
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


async def history(db: AsyncSession, workspace_id: str | None, *, viewer_id: str,
                  limit: int = 50) -> list[dict[str, Any]]:
    query = select(KillSwitchLog, User).outerjoin(User, User.id == KillSwitchLog.user_id).where(
        func.coalesce(KillSwitchLog.details["kind"].as_string(), "") == REASON,
        outside_foreign_private(KillSwitchLog.project_id, viewer_id))
    if workspace_id:
        query = query.where(KillSwitchLog.project_id == workspace_id)
    rows = (await db.execute(query.order_by(KillSwitchLog.created_at.desc()).limit(limit))).all()
    jobs = {log.id: [str(item) for item in (log.details or {}).get("stopped_device_jobs", [])] for log, _by in rows}
    runs = {log.id: [str(item) for item in (log.details or {}).get("paused_runs", [])] for log, _by in rows}
    visible_jobs = await _visible_ids(db, DeviceJob, DeviceJob.workspace_id,
                                      [item for ids in jobs.values() for item in ids], viewer_id)
    visible_runs = await _visible_ids(db, WorkflowRun, WorkflowRun.project_id,
                                      [item for ids in runs.values() for item in ids], viewer_id)
    return [{"id": log.id, "at": log.created_at.isoformat() if log.created_at else None, "reason": log.reason,
             "workspace_id": log.project_id,
             "by": {"id": by.id, "name": by.display_name or by.username} if by else None,
             **_shown(runs[log.id], visible_runs, "paused_runs", "hidden_runs_paused"),
             **_shown(jobs[log.id], visible_jobs, "stopped_device_jobs", "hidden_device_jobs_stopped")}
            for log, by in rows]


__all__ = ["REASON", "EmergencyStopError", "history", "held_by", "new_starts_held", "preview", "resume_new_starts",
           "stop"]
