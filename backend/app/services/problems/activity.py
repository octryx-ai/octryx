"""Activity problems: runs that loop or stand still, and device jobs that stopped talking (live monitoring).

The other collectors judge a run by its status (``paused``/``failed``/waiting a day). These judge it by what it
*does*:

- ``run:looping`` (problem): one item of a running run was *dispatched* (a ``work_item`` event with status
  ``running``) ``LOOP_DISPATCHES`` times inside ``LOOP_WINDOW`` at the same iteration; a replan raises the iteration,
  so the count is per item and plan version. Pending/waiting events (``device_busy``) are not dispatches. A
  looping item can be dispatched 105 times at one iteration in three minutes (210 item sessions) with nothing
  flagging it; healthy team runs dispatch an item at most once per iteration in 5 minutes, and team delivery retries
  an item at most 3 times. The loop guard pauses such a
  run (``loop_guard``).
- ``run:jobs_rejected`` (problem): the device refused ``REJECTED_JOBS`` of the run's jobs inside ``LOOP_WINDOW``
  (e.g. ~105 rejected, ``workspace_preparation_workflow_run_not_bound`` / ``environment_not_ready``). The
  most frequent reason is in the title, because it is what the person has to fix.
- ``run:silent``: a ``running`` run, or one waiting for its device, with no run event and no change of any of its
  device jobs for ``SILENT_ATTENTION`` (attention) or ``SILENT_PROBLEM`` (problem). Runs can go
  an hour without a single event. Runs waiting for a person are left out; they are not silent, they wait.
- ``device:job_stalled`` (problem): a ``running`` device job of a connected device with no event for
  ``JOB_STALLED``. The 10-minute stalled-turn limit (``devices.jobs``) only acts when someone reads the job list;
  past 15 minutes nobody has.

These are signals, not limits: nothing is stopped or refused here.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import PurePosixPath

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.devices.job_state import STATUS_REJECTED
from app.services.devices.job_state import STATUS_RUNNING as JOB_RUNNING

from ...models import DeviceJob, DeviceJobEvent, WorkflowRun, WorkflowRunEvent, WorkflowRunSession
from ..workflow_runs.states import ROLE_MAIN, STATUS_RUNNING, STATUS_WAITING, WAITING_DEVICE
from .links import TARGET_SESSION, TARGET_WORK, fix_link
from .model import KIND_DEVICE, KIND_RUN, SEVERITY_ATTENTION, SEVERITY_PROBLEM, CollectContext, Problem

LOOP_WINDOW = timedelta(minutes=5)
LOOP_DISPATCHES = 10
REJECTED_JOBS = 5
SILENT_ATTENTION = timedelta(minutes=20)
SILENT_PROBLEM = timedelta(minutes=45)
JOB_STALLED = timedelta(minutes=15)

_ACTIVE_RUN = (STATUS_RUNNING, STATUS_WAITING)


def _minutes(delta: timedelta) -> int:
    return max(1, int(delta.total_seconds() // 60))


async def _main_sessions(db: AsyncSession, run_ids: list[str]) -> dict[str, str]:
    if not run_ids:
        return {}
    rows = (await db.execute(
        select(WorkflowRunSession.run_id, func.max(WorkflowRunSession.session_id))
        .where(WorkflowRunSession.run_id.in_(run_ids), WorkflowRunSession.role == ROLE_MAIN)
        .group_by(WorkflowRunSession.run_id)
    )).all()
    return {run_id: session_id for run_id, session_id in rows}


def _run_problem(run: WorkflowRun, session_id: str | None, *, severity: str, code: str, title: str,
                 since: datetime | None, last_seen: datetime | None, count: int = 1) -> Problem:
    fix = (fix_link(TARGET_SESSION, workspace_id=run.project_id, object_id=session_id) if session_id
           else fix_link(TARGET_WORK, workspace_id=run.project_id, object_id=run.work_item_id))
    return Problem(kind=KIND_RUN, severity=severity, object_type="workflow_run", object_id=run.id,
                   object_name=run.title or run.workflow_key, reason_code=code, title=title, since=since,
                   last_seen=last_seen, count=count, workspace_id=run.project_id, fix=fix)


async def _looping(db: AsyncSession, ctx: CollectContext) -> list[tuple[WorkflowRun, dict]]:
    rows = (await db.execute(
        select(WorkflowRun, WorkflowRunEvent.detail, WorkflowRunEvent.created_at)
        .join(WorkflowRun, WorkflowRun.id == WorkflowRunEvent.run_id)
        .where(WorkflowRunEvent.kind == "work_item", WorkflowRunEvent.created_at >= ctx.now - LOOP_WINDOW,
               WorkflowRunEvent.created_at <= ctx.now,  # the window ends now (a replay at an earlier "now" too)
               WorkflowRun.status.in_(_ACTIVE_RUN), ctx.scope(WorkflowRun.project_id))
    )).all()
    runs: dict[str, WorkflowRun] = {}
    seen: dict[tuple[str, str, str], list[datetime]] = defaultdict(list)
    for run, detail, created_at in rows:
        detail = detail if isinstance(detail, dict) else {}
        if detail.get("status") != "running":
            continue  # only a dispatch counts; pending/device_busy is waiting, not work started again
        runs[run.id] = run
        seen[(run.id, str(detail.get("item") or "?"), str(detail.get("iteration") or ""))].append(created_at)
    worst: dict[str, dict] = {}
    for (run_id, item, _iteration), times in seen.items():
        if len(times) >= LOOP_DISPATCHES and len(times) > worst.get(run_id, {}).get("count", 0):
            worst[run_id] = {"item": item, "count": len(times), "iteration": _iteration, "since": min(times),
                             "last": max(times)}
    return [(runs[run_id], found) for run_id, found in worst.items()]


async def looping_runs(db: AsyncSession, ctx: CollectContext) -> list[tuple[WorkflowRun, dict]]:
    """``(run, {item, count, iteration, since, last})`` of every run with a dispatch loop (the loop guard's input)."""
    return await _looping(db, ctx)


async def _rejected(db: AsyncSession, ctx: CollectContext) -> list[tuple[WorkflowRun, dict]]:
    rows = (await db.execute(
        select(WorkflowRun, DeviceJob.status_reason, func.count(), func.min(DeviceJob.created_at),
               func.max(DeviceJob.created_at))
        .join(WorkflowRunSession, WorkflowRunSession.session_id == DeviceJob.session_id)
        .join(WorkflowRun, WorkflowRun.id == WorkflowRunSession.run_id)
        .where(DeviceJob.status == STATUS_REJECTED, DeviceJob.created_at >= ctx.now - LOOP_WINDOW,
               WorkflowRun.status.in_(_ACTIVE_RUN), ctx.scope(WorkflowRun.project_id))
        .group_by(WorkflowRun.id, DeviceJob.status_reason)
    )).all()
    runs: dict[str, WorkflowRun] = {}
    reasons: dict[str, Counter] = defaultdict(Counter)
    span: dict[str, list[datetime]] = defaultdict(list)
    for run, reason, count, first, last in rows:
        runs[run.id] = run
        reasons[run.id][reason or "unknown"] += int(count)
        span[run.id] += [first, last]
    found = []
    for run_id, counter in reasons.items():
        total = sum(counter.values())
        if total >= REJECTED_JOBS:
            found.append((runs[run_id], {"count": total, "reason": counter.most_common(1)[0][0],
                                         "since": min(span[run_id]), "last": max(span[run_id])}))
    return found


async def _silent(db: AsyncSession, ctx: CollectContext) -> list[tuple[WorkflowRun, datetime]]:
    machine_wait = or_(WorkflowRun.status == STATUS_RUNNING,
                       (WorkflowRun.status == STATUS_WAITING) & (WorkflowRun.waiting_kind == WAITING_DEVICE))
    candidates = (await db.execute(
        select(WorkflowRun).where(machine_wait, WorkflowRun.updated_at < ctx.now - SILENT_ATTENTION,
                                  ctx.scope(WorkflowRun.project_id))
        .order_by(WorkflowRun.updated_at).limit(ctx.limit)
    )).scalars().all()
    if not candidates:
        return []
    ids = [run.id for run in candidates]
    last_event = dict((await db.execute(
        select(WorkflowRunEvent.run_id, func.max(WorkflowRunEvent.created_at))
        .where(WorkflowRunEvent.run_id.in_(ids)).group_by(WorkflowRunEvent.run_id)
    )).all())
    last_job = dict((await db.execute(
        select(WorkflowRunSession.run_id, func.max(DeviceJob.updated_at))
        .join(DeviceJob, DeviceJob.session_id == WorkflowRunSession.session_id)
        .where(WorkflowRunSession.run_id.in_(ids)).group_by(WorkflowRunSession.run_id)
    )).all())
    silent = []
    for run in candidates:
        last = max(value for value in (run.updated_at, last_event.get(run.id), last_job.get(run.id)) if value)
        if ctx.now - last >= SILENT_ATTENTION:
            silent.append((run, last))
    return silent


async def _run_problems(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    looping, rejected, silent = await _looping(db, ctx), await _rejected(db, ctx), await _silent(db, ctx)
    sessions = await _main_sessions(db, sorted({run.id for run, _ in (*looping, *rejected, *silent)}))
    problems = []
    for run, found in looping:
        problems.append(_run_problem(
            run, sessions.get(run.id), severity=SEVERITY_PROBLEM, code="looping", count=found["count"],
            title=(f"Loop detected in workflow run {run.title or run.workflow_key}: item {found['item']} was "
                   f"dispatched {found['count']} times in {_minutes(LOOP_WINDOW)} minutes without moving on."),
            since=found["since"], last_seen=found["last"]))
    for run, found in rejected:
        problems.append(_run_problem(
            run, sessions.get(run.id), severity=SEVERITY_PROBLEM, code="jobs_rejected", count=found["count"],
            title=(f"Workflow run {run.title or run.workflow_key}: the device refused {found['count']} jobs in "
                   f"{_minutes(LOOP_WINDOW)} minutes ({found['reason'].replace('_', ' ')})."),
            since=found["since"], last_seen=found["last"]))
    for run, last in silent:
        quiet = ctx.now - last
        severity = SEVERITY_PROBLEM if quiet >= SILENT_PROBLEM else SEVERITY_ATTENTION
        problems.append(_run_problem(
            run, sessions.get(run.id), severity=severity, code="silent",
            title=f"Workflow run {run.title or run.workflow_key} has shown no activity for {_minutes(quiet)} minutes.",
            since=last, last_seen=last))
    return problems


async def _stalled_jobs(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    last_event = (select(DeviceJobEvent.job_id, func.max(DeviceJobEvent.created_at).label("at"))
                  .join(DeviceJob, DeviceJob.id == DeviceJobEvent.job_id)
                  .where(DeviceJob.status == JOB_RUNNING).group_by(DeviceJobEvent.job_id).subquery())
    workspace = func.coalesce(DeviceJob.workspace_id, "")
    rows = (await db.execute(
        select(DeviceJob, last_event.c.at)
        .outerjoin(last_event, last_event.c.job_id == DeviceJob.id)
        .where(DeviceJob.status == JOB_RUNNING, DeviceJob.disconnected_at.is_(None),
               DeviceJob.updated_at < ctx.now - JOB_STALLED, ctx.scope(workspace))
        .order_by(DeviceJob.updated_at).limit(ctx.limit)
    )).all()
    problems = []
    for job, event_at in rows:
        last = max(value for value in (job.updated_at, event_at) if value)
        if ctx.now - last < JOB_STALLED:
            continue
        name = PurePosixPath(job.folder or "").name or job.id
        problems.append(Problem(
            kind=KIND_DEVICE, severity=SEVERITY_PROBLEM, object_type="device_job", object_id=job.id,
            object_name=name, reason_code="job_stalled",
            title=f"Device job {name} is running but has sent nothing for {_minutes(ctx.now - last)} minutes.",
            since=last, last_seen=last, workspace_id=job.workspace_id or None,
            fix=fix_link(TARGET_SESSION, workspace_id=job.workspace_id, object_id=job.session_id)))
    return problems


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    return [*await _run_problems(db, ctx), *await _stalled_jobs(db, ctx)]


__all__ = ["JOB_STALLED", "LOOP_DISPATCHES", "LOOP_WINDOW", "REJECTED_JOBS", "SILENT_ATTENTION", "SILENT_PROBLEM",
           "collect", "looping_runs"]
