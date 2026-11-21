"""Activity problems in the person's attention queue: their run loops or stands still, their device job stalls.

A run can loop for minutes without anyone being told. The
Problems list knows it, but nobody looks at a list while a run is working. The attention queue is what
reaches a person: the companion, the inbox and, through ``MobilePushSweeper``, a push on the paired phone (group
"problem", on by default). So every activity problem becomes an entry here for the people it concerns:

- run problems (``looping``, ``jobs_rejected``, ``silent``): the run's requester and its responsible person;
- ``job_stalled``: the job's owner (the only one who can stop it).

``key`` is ``activity:{problem key}:{since}`` for a run that went silent or a job that stalled (``since`` is the last
sign of life, so it stays while the silence lasts and a new silence notifies again). A loop's ``since`` slides with its
5-minute window, so ``looping``/``jobs_rejected`` are keyed without it: one notification per run and code.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Project, User, WorkflowRun
from ...time_utils import utc_now
from ..problems import activity
from ..problems.model import CollectContext, Problem, iso

_SEVERITY = {"problem": "warning", "attention": "warning"}
_SLIDING = frozenset({"looping", "jobs_rejected"})


def entry_key(problem: Problem) -> str:
    if problem.reason_code in _SLIDING:
        return f"activity:{problem.key}"
    return f"activity:{problem.key}:{iso(problem.since) or ''}"


async def _concerned(db: AsyncSession, user: User, problems: list[Problem]) -> list[Problem]:
    run_ids = {p.object_id for p in problems if p.object_type == "workflow_run"}
    job_ids = {p.object_id for p in problems if p.object_type == "device_job"}
    mine: set[str] = set()
    if run_ids:
        mine |= set((await db.execute(select(WorkflowRun.id).where(
            WorkflowRun.id.in_(run_ids),
            (WorkflowRun.requested_by == user.id) | (WorkflowRun.responsible_user_id == user.id)))).scalars())
    if job_ids:
        mine |= set((await db.execute(select(DeviceJob.id).where(
            DeviceJob.id.in_(job_ids), DeviceJob.owner_user_id == user.id))).scalars())
    return [p for p in problems if p.object_id in mine]


async def activity_entries(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    problems = await activity.collect(db, CollectContext(now=utc_now()))
    mine = await _concerned(db, user, problems)
    ids = {p.workspace_id for p in mine if p.workspace_id}
    names = dict((await db.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all()) if ids else {}
    entries = []
    for problem in mine:
        workspace = ({"id": problem.workspace_id, "name": names.get(problem.workspace_id) or problem.workspace_id}
                     if problem.workspace_id else None)
        entries.append({
            "key": entry_key(problem), "kind": "problem", "id": problem.object_id,
            # The phone shows ``title`` as the push text: the sentence that says what is wrong.
            "title": problem.title, "subtitle": problem.object_name,
            "text": problem.title, "created_at": iso(problem.last_seen or problem.since),
            "severity": _SEVERITY.get(problem.severity, "warning"), "code": problem.reason_code,
            "problem": problem.to_dict(), "link": dict(problem.fix), "actions": [],
            "workspace": workspace,
        })
    return entries


__all__ = ["activity_entries", "entry_key"]
