"""``run`` problems: workflow runs that stopped or wait too long, and actions (tasks) whose runs fail.

- ``workflow_runs``: ``paused`` (a limit stopped it, ``pause_reason``) is a problem; ``failed`` is a problem when
  it failed inside the window; ``waiting`` with no change for more than 24 hours needs attention (a run waiting on
  its own sub-workflow is left out: the child reports itself). ``since`` is ``updated_at``, ``count`` 1.
- ``task_runs``: per action, the ``failed``/``error`` runs after its last ``completed`` run inside the window are
  one problem (``count`` failed runs, ``since`` the first of them). The scheduler records a good run as
  ``success``; ``completed`` is accepted too.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Task, TaskRun, WorkflowRun, WorkflowRunSession
from ..workflow_runs.states import (
    ROLE_MAIN,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_WAITING,
    WAITING_SUB_WORKFLOW,
)
from .links import TARGET_SESSION, TARGET_TASKS, TARGET_WORK, fix_link
from .model import KIND_RUN, SEVERITY_ATTENTION, SEVERITY_PROBLEM, CollectContext, Problem

WAITING_TOO_LONG = timedelta(hours=24)
EMERGENCY_STOP = "emergency_stop"  # the pause reason of services/operations/emergency_stop.py
LOOP_DETECTED = "loop_detected"  # the pause reason of loop_guard.py
TASK_FAILED_STATUSES = ("failed", "error")
TASK_SUCCEEDED = ("success", "completed")


def _run_fix(run: WorkflowRun, session_id: str | None) -> dict[str, str]:
    if session_id:
        return fix_link(TARGET_SESSION, workspace_id=run.project_id, object_id=session_id)
    return fix_link(TARGET_WORK, workspace_id=run.project_id, object_id=run.work_item_id)


def _run_problem(run: WorkflowRun, session_id: str | None) -> Problem:
    name = run.title or run.workflow_key
    if run.status == STATUS_PAUSED and run.pause_reason == EMERGENCY_STOP:
        # An admin stopped it on purpose: listed so it is not forgotten, but not broadcast as a problem.
        severity, code = SEVERITY_ATTENTION, "stopped"
        title = f"Workflow run {name} was stopped by an emergency stop; Continue resumes it."
    elif run.status == STATUS_PAUSED and run.pause_reason == LOOP_DETECTED:
        pause = dict(dict(run.node_state or {}).get("pause") or {})
        severity, code = SEVERITY_PROBLEM, "paused"
        title = (f"Loop detected: workflow run {name} was paused automatically (item {pause.get('item')} dispatched "
                 f"{pause.get('count')} times in {pause.get('window_minutes')} minutes).")
    elif run.status == STATUS_PAUSED:
        reason = str(run.pause_reason or "paused")
        severity, code = SEVERITY_PROBLEM, "paused"
        title = f"Workflow run {name} is paused ({reason.replace('_', ' ')})."
    elif run.status == STATUS_FAILED:
        severity, code, title = SEVERITY_PROBLEM, "failed", f"Workflow run {name} failed."
    else:
        severity, code = SEVERITY_ATTENTION, "waiting"
        title = f"Workflow run {name} has been waiting for more than 24 hours."
    return Problem(kind=KIND_RUN, severity=severity, object_type="workflow_run", object_id=run.id, object_name=name,
                   reason_code=code, title=title, since=run.updated_at, last_seen=run.updated_at,
                   workspace_id=run.project_id, fix=_run_fix(run, session_id))


async def _workflow_runs(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    main_session = (select(WorkflowRunSession.run_id, func.max(WorkflowRunSession.session_id).label("session_id"))
                    .where(WorkflowRunSession.role == ROLE_MAIN, WorkflowRunSession.active.is_(True))
                    .group_by(WorkflowRunSession.run_id).subquery())
    stuck = or_(
        WorkflowRun.status == STATUS_PAUSED,
        and_(WorkflowRun.status == STATUS_FAILED, WorkflowRun.updated_at >= ctx.window_start),
        and_(WorkflowRun.status == STATUS_WAITING, WorkflowRun.updated_at < ctx.now - WAITING_TOO_LONG,
             or_(WorkflowRun.waiting_kind.is_(None), WorkflowRun.waiting_kind != WAITING_SUB_WORKFLOW)),
    )
    rows = (await db.execute(
        select(WorkflowRun, main_session.c.session_id)
        .outerjoin(main_session, main_session.c.run_id == WorkflowRun.id)
        .where(stuck, ctx.scope(WorkflowRun.project_id))
        .order_by(WorkflowRun.updated_at.desc()).limit(ctx.limit)
    )).all()
    return [_run_problem(run, session_id) for run, session_id in rows]


async def _task_runs(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    last_ok = (select(TaskRun.task_id, func.max(TaskRun.started_at).label("ok_at"))
               .where(TaskRun.status.in_(TASK_SUCCEEDED), TaskRun.started_at >= ctx.window_start)
               .group_by(TaskRun.task_id).subquery())
    rows = (await db.execute(
        select(Task.id, Task.name, Task.project_id, func.min(TaskRun.started_at), func.max(TaskRun.started_at),
               func.count(), func.max(TaskRun.session_id))
        .join(Task, Task.id == TaskRun.task_id)
        .outerjoin(last_ok, last_ok.c.task_id == TaskRun.task_id)
        .where(TaskRun.status.in_(TASK_FAILED_STATUSES), TaskRun.started_at >= ctx.window_start,
               or_(last_ok.c.ok_at.is_(None), TaskRun.started_at > last_ok.c.ok_at), ctx.scope(Task.project_id))
        .group_by(Task.id, Task.name, Task.project_id)
        .order_by(func.max(TaskRun.started_at).desc()).limit(ctx.limit)
    )).all()
    problems = []
    for task_id, name, project_id, first, last, count, session_id in rows:
        runs = "run" if count == 1 else "runs"
        problems.append(Problem(
            kind=KIND_RUN, severity=SEVERITY_PROBLEM, object_type="task", object_id=task_id, object_name=name,
            reason_code="runs_failed", title=f"Action {name}: {count} failed {runs} since the last success.",
            since=first, last_seen=last, count=int(count), workspace_id=project_id,
            fix=(fix_link(TARGET_SESSION, workspace_id=project_id, object_id=session_id) if session_id
                 else fix_link(TARGET_TASKS, object_id=task_id)),
        ))
    return problems


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    return [*await _workflow_runs(db, ctx), *await _task_runs(db, ctx)]


__all__ = ["TASK_FAILED_STATUSES", "WAITING_TOO_LONG", "collect"]
