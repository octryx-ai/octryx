"""The runs of Operations › Live: every active run with its place, cost, items, jobs and activity problems.

One monitoring view for all agents shows where each piece of work is. Before this, the answer was
spread over ``workflow_runs`` (status, node), ``context.work`` (items), ``sessions``/``device_jobs`` (where, cost)
and ``workflow_run_events`` (activity), and only readable one run and one Workspace at a time.

Cost of a run (``operations/costs.run_cost_split``): ``cost_usd`` is the API cost of the ``usage_events`` of its
sessions; ``seat_api_equivalent_usd`` beside it is what its seat calls would have cost through the API,
never added to the cost.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Project, User, WorkflowRun, WorkflowRunEvent, WorkflowRunSession
from ...models.runtime.secure_work import WorkItem
from ..attention.running import run_state
from ..problems.activity import LOOP_WINDOW
from ..problems.model import SEVERITY_PROBLEM, Problem, iso
from ..workflow_runs.states import ROLE_MAIN, STATUS_PAUSED, STATUS_RUNNING, STATUS_WAITING
from ..workflow_runs.teamwork import work_of
from .costs import RunCost, run_cost_split
from .emergency_stop import REASON as EMERGENCY_STOP

ACTIVE = (STATUS_RUNNING, STATUS_WAITING, STATUS_PAUSED)
STATES = ("looping", "problem", "silent", "needs_you", "stopped", "working")
_LOOP_CODES = frozenset({"looping", "jobs_rejected"})


def person(user: User | None, viewer_id: str) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "name": user.display_name or user.username, "is_me": user.id == viewer_id}


def problem_ref(problem: Problem) -> dict[str, Any]:
    return {"key": problem.key, "reason_code": problem.reason_code, "severity": problem.severity,
            "title": problem.title}


def workflow_title(title: str | None, key: str | None) -> str | None:
    """The run title without its ticket key: runs are titled "Ticket delivery · <key>", and the page shows the key
    from ``work_item`` already (it would appear twice)."""
    if not title or not key:
        return title
    parts = [part for part in title.split(" · ") if part.strip() != key]
    return " · ".join(parts) or title


def state_of(run: WorkflowRun, problems: list[Problem]) -> str:
    """``looping`` > ``problem`` > ``silent`` > ``needs_you`` > ``stopped`` > ``working`` (the most urgent wins).

    ``stopped``: paused by a deliberate emergency stop. An admin chose it, so it is not a problem (otherwise
    the problem count would rise by every stopped run); Continue resumes it.
    """
    codes = {item.reason_code for item in problems}
    if codes & _LOOP_CODES:
        return "looping"
    if run.status == STATUS_PAUSED and run.pause_reason == EMERGENCY_STOP:
        return "stopped"
    if run.status == STATUS_PAUSED or any(item.severity == SEVERITY_PROBLEM and item.reason_code != "silent"
                                          for item in problems):
        return "problem"
    if "silent" in codes:
        return "silent"
    return "needs_you" if run_state(run) == "needs_you" else "working"


async def _node_titles(db: AsyncSession, runs: list[WorkflowRun]) -> dict[str, str]:
    from ..workflow_runs.views import run_nodes

    titles = {}
    for run in runs:
        if not run.current_node_id:
            continue
        try:
            nodes = await run_nodes(db, run, user=None)
        except Exception:  # noqa: BLE001 - a run of an unpublished flow is still listed, with its node id
            nodes = []
        node = next((item for item in nodes if item.get("id") == run.current_node_id), None)
        titles[run.id] = str((node or {}).get("title") or run.current_node_id)
    return titles


class _RunFacts:
    """Everything the run rows need, read with one query per table for all runs together."""

    def __init__(self) -> None:
        self.last_event: dict[str, datetime] = {}
        self.sessions: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.jobs: dict[str, DeviceJob] = {}
        self.costs: dict[str, RunCost] = {}
        self.dispatches: Counter = Counter()

    async def read(self, db: AsyncSession, ids: list[str], now: datetime) -> _RunFacts:
        self.last_event = dict((await db.execute(
            select(WorkflowRunEvent.run_id, func.max(WorkflowRunEvent.created_at))
            .where(WorkflowRunEvent.run_id.in_(ids)).group_by(WorkflowRunEvent.run_id))).all())
        for run_id, session_id, role in (await db.execute(
                select(WorkflowRunSession.run_id, WorkflowRunSession.session_id, WorkflowRunSession.role)
                .where(WorkflowRunSession.run_id.in_(ids)).order_by(WorkflowRunSession.linked_at))).all():
            self.sessions[run_id].append((session_id, role))
        session_ids = sorted({sid for pairs in self.sessions.values() for sid, _ in pairs})
        if session_ids:
            for job in (await db.execute(select(DeviceJob).where(DeviceJob.session_id.in_(session_ids))
                                         .order_by(DeviceJob.created_at))).scalars():
                self.jobs[job.session_id] = job  # the newest job of each session
        self.costs = await run_cost_split(db, ids)  # one cost rule for Live and the cost report
        for run_id, detail in (await db.execute(
                select(WorkflowRunEvent.run_id, WorkflowRunEvent.detail)
                .where(WorkflowRunEvent.run_id.in_(ids), WorkflowRunEvent.kind == "work_item",
                       WorkflowRunEvent.created_at >= now - LOOP_WINDOW))).all():
            self.dispatches[(run_id, str((detail or {}).get("item") or ""))] += 1
        return self

    def main_session(self, run_id: str) -> str | None:
        mains = [sid for sid, role in self.sessions.get(run_id, []) if role == ROLE_MAIN]
        return mains[-1] if mains else None


def _job_view(job: DeviceJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {"id": job.id, "status": job.status, "status_reason": job.status_reason, "turn_state": job.turn_state,
            "folder": job.folder, "device_id": job.device_id, "model": job.turn_model or job.model,
            "last_event_at": iso(job.updated_at)}  # no cost: the job's calls are the run's usage rows


def _items(run: WorkflowRun, facts: _RunFacts, job_problems: dict[str, list[Problem]]) -> list[dict[str, Any]]:
    from ..workflow_runs.teamwork.item_order import plan_order

    items = dict(work_of(run).get("items") or {})
    rows = []
    for key in plan_order(items) if items else []:
        item = dict(items[key] or {})
        job = facts.jobs.get(str(item.get("session_id") or ""))
        rows.append({
            "id": key, "title": item.get("title"), "status": item.get("status"), "iteration": item.get("iteration"),
            "model": item.get("model"), "branch": item.get("branch"), "session_id": item.get("session_id"),
            "started_at": item.get("started_at"), "finished_at": item.get("finished_at"),
            "dispatches_5m": facts.dispatches[(run.id, key)], "job": _job_view(job),
            "problems": [problem_ref(p) for p in job_problems.get(job.id, [])] if job is not None else [],
        })
    return rows


async def live_runs(db: AsyncSession, *, viewer_id: str, scope: Any, now: datetime,
                    problems: list[Problem]) -> list[dict[str, Any]]:
    from ..workflow_runs.runtime_target.target import target_view

    runs = list((await db.execute(
        select(WorkflowRun).where(WorkflowRun.status.in_(ACTIVE), scope(WorkflowRun.project_id))
        .order_by(WorkflowRun.updated_at.desc()))).scalars())
    if not runs:
        return []
    facts = await _RunFacts().read(db, [run.id for run in runs], now)
    run_problems: dict[str, list[Problem]] = defaultdict(list)
    job_problems: dict[str, list[Problem]] = defaultdict(list)
    for problem in problems:
        target = run_problems if problem.object_type == "workflow_run" else job_problems
        target[problem.object_id].append(problem)
    people = {user.id: user for user in (await db.execute(select(User).where(User.id.in_(
        {uid for run in runs for uid in (run.requested_by, run.responsible_user_id) if uid})))).scalars()}
    projects = dict((await db.execute(select(Project.id, Project.name)
                                      .where(Project.id.in_({run.project_id for run in runs})))).all())
    items = {item.id: item for item in (await db.execute(select(WorkItem).where(WorkItem.id.in_(
        {run.work_item_id for run in runs if run.work_item_id})))).scalars()}
    titles = await _node_titles(db, runs)
    rows = []
    for run in runs:
        # A run's stalled item jobs are its problems too: they decide its state.
        mine = run_problems[run.id] + [p for sid, _ in facts.sessions.get(run.id, [])
                                       if sid in facts.jobs for p in job_problems.get(facts.jobs[sid].id, [])]
        last = max(value for value in (run.updated_at, facts.last_event.get(run.id)) if value)
        item = items.get(run.work_item_id or "")
        rows.append({
            "id": run.id, "title": run.title, "workflow_key": run.workflow_key,
            "workflow_title": workflow_title(run.title, item.source_key if item else None),
            "workspace": {"id": run.project_id, "name": projects.get(run.project_id) or run.project_id},
            "work_item": {"id": item.id, "key": item.source_key, "title": item.title} if item else None,
            "state": state_of(run, mine), "status": run.status, "waiting_kind": run.waiting_kind,
            # Why a paused run stopped (e.g. ``emergency_stop``), so the live view can say it in words.
            "pause_reason": run.pause_reason if run.status == STATUS_PAUSED else None,
            "current_node": {"id": run.current_node_id, "title": titles.get(run.id)} if run.current_node_id else None,
            "started_at": iso(run.created_at), "last_event_at": iso(last),
            "idle_seconds": max(0, int((now - last).total_seconds())),
            "requested_by": person(people.get(run.requested_by), viewer_id),
            "responsible": person(people.get(run.responsible_user_id or ""), viewer_id),
            "where": target_view(run), **(facts.costs.get(run.id) or RunCost()).as_dict(),
            "budget_usage": run.budget_usage or None,
            "session_id": facts.main_session(run.id),
            "problems": [problem_ref(p) for p in run_problems[run.id]],
            "items": _items(run, facts, job_problems),
        })
    rows.sort(key=lambda row: (STATES.index(row["state"]), row["idle_seconds"]))
    return rows


__all__ = ["ACTIVE", "STATES", "live_runs", "person", "state_of", "workflow_title"]
