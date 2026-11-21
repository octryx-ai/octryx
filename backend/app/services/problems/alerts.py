"""Problem alerts: a problem with a run or a device job is announced once when it appears and once when it clears.

Without this nothing under ``services/workflow_runs``, ``devices`` or ``problems`` calls
``create_notification`` or emits a webhook; a paused, failed, looping or stalled run is pull-only. The attention
queue tells the run's own people; this tells the people who look after a Workspace and the team's
channels:

- **raised** (severity ``problem`` only; ``attention`` stays in the lists): an in-app notification
  ``problem.raised`` to the Workspace's admins and owners (the platform admins when it has none) and to the object's
  own people (requester and responsible of a run, owner of a device job), so their personal subscriptions fire;
  the Workspace's notification subscriptions (email, Slack, Teams) get the same through
  ``enqueue_project_notification_deliveries``; outbound webhooks get ``problem.raised``.
- **cleared**: the problem is gone (the run moved on, was stopped, the job ended): webhooks get ``problem.cleared``.

Two guards (an installation may already hold many paused or failed runs when alerts start):

- **baseline**: the first sweep ever (no ``problems.raised``/``cleared`` row yet) records every open problem as raised
  *silently* and sends nothing; only problems that appear afterwards are announced. A silently recorded problem
  that clears is recorded as cleared without a webhook (nobody was told it began).
- **burst**: at most ``MAX_ANNOUNCED_PER_SWEEP`` problems are announced one by one per sweep (newest first); the
  rest are recorded silently and each Workspace gets one summary ("N more problems") with a link to its Problems
  list, so a future loop over many runs cannot flood admins, email/Slack/Teams or webhooks. Nothing is dropped:
  every problem stays in the Problems list and the audit log.

State without a new table: like acknowledgements, an ``audit_log`` row per transition (``problems.raised`` /
``problems.cleared``, ``resource_id`` = the problem key, ``user_id`` = the run's requester or the job's owner). That
row is also the record of who was told what, when.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...models import AuditLog, DeviceJob, Role, User, UserProject, UserRole, WorkflowRun
from ...time_utils import utc_now
from ..admin.governance.admin_access_service import PROJECT_ADMIN_ROLES
from . import activity, runs
from .model import SEVERITY_PROBLEM, CollectContext, Problem, iso

logger = logging.getLogger(__name__)

ACTION_RAISED = "problems.raised"
ACTION_CLEARED = "problems.cleared"
# The first sweep leaves this marker, so a platform with nothing open yet is not baselined again and again.
ACTION_BASELINE = "problems.alerts_baseline"
EVENT_RAISED = "problem.raised"
EVENT_CLEARED = "problem.cleared"
MAX_ANNOUNCED_PER_SWEEP = 10
INTERVAL_SECONDS = 60
COLLECTORS = (activity.collect, runs.collect)


async def _current(db: AsyncSession, now) -> dict[str, Problem]:
    ctx = CollectContext(now=now)
    found: dict[str, Problem] = {}
    for collector in COLLECTORS:
        for problem in await collector(db, ctx):
            if problem.severity == SEVERITY_PROBLEM and problem.object_type in ("workflow_run", "device_job"):
                found.setdefault(problem.key, problem)
    return found


async def open_alerts(db: AsyncSession, now=None) -> dict[str, dict[str, Any]]:
    """``key -> details`` of every alert whose latest transition is ``raised`` (no age limit: a paused run stays
    paused for weeks and must not be announced again every week)."""
    rows = (await db.execute(
        select(AuditLog.resource_id, AuditLog.action, AuditLog.details)
        .where(AuditLog.resource_type == "problem", AuditLog.action.in_((ACTION_RAISED, ACTION_CLEARED)))
        .order_by(AuditLog.created_at.asc()))).all()
    latest: dict[str, tuple[str, dict]] = {}
    for key, action, details in rows:
        latest[str(key)] = (action, details if isinstance(details, dict) else {})
    return {key: details for key, (action, details) in latest.items() if action == ACTION_RAISED}


async def _person(db: AsyncSession, problem: Problem) -> tuple[str | None, dict[str, Any], set[str]]:
    """The object's person (audit actor), the payload's ids and the object's own people (requester and
    responsible of a run, owner of a job): their personal email/Slack/Teams subscriptions fire for their own work
    too, not only the attention queue."""
    if problem.object_type == "workflow_run":
        run = await db.get(WorkflowRun, problem.object_id)
        people = {uid for uid in (run.requested_by, run.responsible_user_id) if uid} if run else set()
        return (run.requested_by if run else None), {"run_id": problem.object_id}, people
    job = await db.get(DeviceJob, problem.object_id)
    return ((job.owner_user_id if job else None),
            {"device_job_id": problem.object_id, "session_id": job.session_id if job else None},
            {job.owner_user_id} if job else set())


async def _workspace_admins(db: AsyncSession, workspace_id: str | None) -> list[str]:
    if workspace_id:
        ids = list((await db.execute(select(UserProject.user_id).join(User, User.id == UserProject.user_id).where(
            UserProject.project_id == workspace_id, UserProject.role.in_(sorted(PROJECT_ADMIN_ROLES)),
            User.is_active))).scalars())
        if ids:
            return sorted(set(ids))
    return sorted(set((await db.execute(select(User.id).join(UserRole, UserRole.user_id == User.id)
                                        .join(Role, Role.id == UserRole.role_id)
                                        .where(Role.name == "admin", User.is_active))).scalars()))


def payload(problem: Problem, ids: dict[str, Any]) -> dict[str, Any]:
    return {"key": problem.key, "kind": problem.kind, "reason_code": problem.reason_code,
            "severity": problem.severity, "title": problem.title, "workspace_id": problem.workspace_id,
            "object": {"type": problem.object_type, "id": problem.object_id, "name": problem.object_name},
            "since": iso(problem.since), "url": problem.fix.get("href"), **ids}


async def _tell(db: AsyncSession, workspace_id: str | None, *, title: str, body: str, link: str | None,
                data: dict[str, Any], people: set[str] | frozenset[str] = frozenset()) -> None:
    from ..notification_delivery import enqueue_project_notification_deliveries
    from ..outbound_webhook.delivery import emit_outbound_webhook_event
    from ..team_notification.service import create_notification

    for user_id in sorted(set(await _workspace_admins(db, workspace_id)) | set(people)):
        await create_notification(db, user_id=user_id, notification_type=EVENT_RAISED, title=title, body=body,
                                  link=link, payload=data, project_id=workspace_id)
    if workspace_id:
        await enqueue_project_notification_deliveries(db, notification_type=EVENT_RAISED, title=title, body=body,
                                                      link=link, payload=data, project_id=workspace_id)
    await emit_outbound_webhook_event(db, event_type=EVENT_RAISED, payload=data, project_id=workspace_id)


async def _raise(db: AsyncSession, problem: Problem, *, silent: str | None = None) -> bool:
    """Record the problem as raised; announce it unless ``silent`` names why not. False when its object is gone."""
    actor, ids, people = await _person(db, problem)
    if actor is None:
        return False  # the object is gone; nothing to announce
    body = payload(problem, ids)
    if silent is None:
        await _tell(db, problem.workspace_id, title=problem.title, body=problem.object_name, link=body["url"],
                    data=body, people=people)
    db.add(AuditLog(user_id=actor, action=ACTION_RAISED, resource_type="problem", resource_id=problem.key,
                    details={**body, "actor": "platform", **({"silent": silent} if silent else {})}))
    return True


def _problems_link(workspace_id: str | None) -> str:
    from .links import TARGET_WORK, fix_link

    return fix_link(TARGET_WORK, workspace_id=workspace_id)["href"]


async def _summaries(db: AsyncSession, held: list[Problem], now) -> None:
    by_workspace: dict[str | None, list[Problem]] = defaultdict(list)
    for problem in held:
        by_workspace[problem.workspace_id].append(problem)
    for workspace_id, problems in by_workspace.items():
        count = len(problems)
        title = f"{count} more {'problem' if count == 1 else 'problems'} with runs or device jobs."
        link = _problems_link(workspace_id)
        await _tell(db, workspace_id, title=title, body="See the Problems list.", link=link, data={
            "key": f"summary:{workspace_id or 'platform'}:{iso(now)}", "kind": "summary", "reason_code": "summary",
            "severity": SEVERITY_PROBLEM, "title": title, "workspace_id": workspace_id, "count": count,
            "keys": [problem.key for problem in problems], "url": link})


async def _clear(db: AsyncSession, key: str, details: dict[str, Any]) -> None:
    from ..outbound_webhook.delivery import emit_outbound_webhook_event

    actor = (await db.execute(select(AuditLog.user_id).where(
        AuditLog.resource_id == key, AuditLog.action == ACTION_RAISED).order_by(AuditLog.created_at.desc())
        .limit(1))).scalar_one_or_none()
    body = {**{k: v for k, v in details.items() if k not in ("actor", "silent")}, "cleared_at": iso(utc_now())}
    if not details.get("silent"):  # nobody was told it began: nobody is told it ended
        await emit_outbound_webhook_event(db, event_type=EVENT_CLEARED, payload=body,
                                          project_id=details.get("workspace_id"))
    if actor:
        db.add(AuditLog(user_id=actor, action=ACTION_CLEARED, resource_type="problem", resource_id=key,
                        details=body))


async def _has_history(db: AsyncSession) -> bool:
    return (await db.execute(select(AuditLog.id).where(
        AuditLog.resource_type == "problem", AuditLog.action.in_((ACTION_RAISED, ACTION_CLEARED, ACTION_BASELINE)))
        .limit(1))).first() is not None


async def _mark_baseline(db: AsyncSession, recorded: int) -> None:
    admins = await _workspace_admins(db, None)
    if admins:  # a fresh install without an admin is simply baselined again on the next sweep
        db.add(AuditLog(user_id=admins[0], action=ACTION_BASELINE, resource_type="problem", resource_id="alerts",
                        details={"actor": "platform", "recorded_silently": recorded}))


async def sweep(db: AsyncSession, *, now=None) -> dict[str, int]:
    """Announce new problems and cleared ones. The caller commits."""
    now = now or utc_now()
    # a looping run is paused first; this sweep then announces it as paused.
    from .loop_guard import pause_looping_runs

    guarded = await pause_looping_runs(db, now=now)
    baseline = not await _has_history(db)
    current, already = await _current(db, now), await open_alerts(db, now)
    new = sorted((problem for key, problem in current.items() if key not in already),
                 key=lambda problem: (problem.last_seen or problem.since or now), reverse=True)
    cleared = [(key, details) for key, details in already.items() if key not in current]
    announced, held = ([], new) if baseline else (new[:MAX_ANNOUNCED_PER_SWEEP], new[MAX_ANNOUNCED_PER_SWEEP:])
    for problem in announced:
        await _raise(db, problem)
    recorded = [problem for problem in held if await _raise(db, problem, silent="baseline" if baseline else "burst")]
    if baseline:
        await _mark_baseline(db, len(recorded))
    elif recorded:
        await _summaries(db, recorded, now)
    for key, details in cleared:
        await _clear(db, key, details)
    await db.flush()
    return {"raised": len(announced), "held": len(recorded), "baseline": int(baseline), "cleared": len(cleared),
            "paused_loops": len(guarded)}


class ProblemAlertWorker:
    """Runs :func:`sweep` every minute; a failing sweep is logged and tried again."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = INTERVAL_SECONDS):
        self._session_factory = session_factory
        self._interval_seconds = max(15, int(interval_seconds))
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        while True:
            try:
                async with self._session_factory() as db:
                    await sweep(db)
                    await db.commit()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the next sweep tries again
                logger.exception("problem_alert_sweep_failed")
            await asyncio.sleep(self._interval_seconds)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="problem-alert-worker")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


__all__ = ["ACTION_CLEARED", "ACTION_RAISED", "EVENT_CLEARED", "EVENT_RAISED", "MAX_ANNOUNCED_PER_SWEEP",
           "ProblemAlertWorker", "open_alerts", "payload", "sweep"]
