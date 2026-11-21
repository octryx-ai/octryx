"""Problem alerts: a run's problem is announced once to the Workspace's admins, its channels and webhooks, and once
more as cleared when it is gone (paused, failed, looping and stalled runs are not pull-only).

Guards: the first sweep is a silent baseline of what is open already, and a burst of new problems is announced up to
a cap plus one summary per Workspace."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    AuditLog,
    Notification,
    OutboundWebhook,
    OutboundWebhookDelivery,
    Project,
    User,
    UserProject,
    WorkflowRun,
    WorkflowRunEvent,
)
from app.services.problems import alerts
from app.time_utils import utc_now


def uid() -> str:
    return str(uuid.uuid4())


async def _user(db, label: str, project: Project, role: str) -> User:
    user = User(id=uid(), username=f"{label}-{uid()[:8]}", email=f"{uid()}@example.test", password_hash="!")
    db.add(user)
    await db.flush()
    db.add(UserProject(user_id=user.id, project_id=project.id, role=role))
    await db.flush()
    return user


async def _world(db) -> dict:
    project = Project(id=uid(), name="Kitchen helper", is_active=True, config={})
    db.add(project)
    await db.flush()
    owner = await _user(db, "owner", project, "member")
    lead = await _user(db, "lead", project, "admin")
    member = await _user(db, "member", project, "member")
    hook = OutboundWebhook(id=uid(), project_id=project.id, created_by=lead.id, name="Team channel",
                           url="https://hooks.example.test/x", secret_hash="h", encrypted_secret="s",
                           event_types_json=json.dumps(["problem.raised", "problem.cleared"]), is_active=True)
    db.add(hook)
    await db.flush()
    return {"project": project, "owner": owner, "lead": lead, "member": member, "hook": hook}


def _run(w: dict, status: str = "running", **extra) -> WorkflowRun:
    return WorkflowRun(id=uid(), project_id=w["project"].id, workflow_kind="phased", workflow_key="team-delivery",
                       title=extra.pop("title", "Team delivery"), status=status, requested_by=w["owner"].id,
                       updated_at=extra.pop("updated_at", utc_now()), **extra)


def _loop(db, run: WorkflowRun, now) -> None:
    for n in range(12):
        db.add(WorkflowRunEvent(run_id=run.id, kind="work_item", created_at=now - timedelta(seconds=3 * n),
                                detail={"item": "core-domain", "status": "running", "iteration": 1}))


async def _deliveries(db, hook, event: str) -> list[dict]:
    rows = (await db.execute(select(OutboundWebhookDelivery).where(
        OutboundWebhookDelivery.webhook_id == hook.id, OutboundWebhookDelivery.event_type == event))).scalars()
    return [json.loads(item.payload_json)["payload"] for item in rows]


@pytest.mark.asyncio
async def test_the_first_sweep_is_a_silent_baseline_of_what_is_open_already(db):
    w = await _world(db)
    now = utc_now()
    old = _run(w, "paused", title="Rehearsal R2", pause_reason="loop_limit")
    db.add(old)
    await db.flush()

    first = await alerts.sweep(db, now=now)

    assert first["baseline"] == 1 and first["raised"] == 0
    assert f"run:{old.id}:paused" in await alerts.open_alerts(db)
    assert await _deliveries(db, w["hook"], "problem.raised") == []
    assert not (await db.execute(select(Notification).where(Notification.type == "problem.raised"))).first()
    # It is resumed later: nobody was told it began, so nobody is told it ended.
    old.status = "running"
    await db.flush()
    await alerts.sweep(db, now=now + timedelta(minutes=1))
    assert await _deliveries(db, w["hook"], "problem.cleared") == []
    assert f"run:{old.id}:paused" not in await alerts.open_alerts(db)


@pytest.mark.asyncio
async def test_a_new_loop_is_raised_once_to_the_workspace_admins_and_webhooks_and_cleared_when_it_stops(db):
    w = await _world(db)
    now = utc_now()
    await alerts.sweep(db, now=now)  # the platform has been watching already
    run = _run(w)
    db.add(run)
    await db.flush()
    _loop(db, run, now)
    await db.flush()
    # The loop guard pauses the looping run in the same sweep, so it is announced as paused.
    key = f"run:{run.id}:paused"

    first = await alerts.sweep(db, now=now)
    again = await alerts.sweep(db, now=now + timedelta(seconds=30))

    assert first["raised"] >= 1 and first["baseline"] == 0 and again["raised"] == 0
    notes = (await db.execute(select(Notification).where(Notification.type == "problem.raised"))).scalars().all()
    told = {note.user_id for note in notes if note.title.startswith("Loop detected")}
    assert w["lead"].id in told and w["owner"].id in told and w["member"].id not in told
    looping = [item for item in await _deliveries(db, w["hook"], "problem.raised") if item["key"] == key]
    assert len(looping) == 1
    assert (looping[0]["run_id"], looping[0]["reason_code"]) == (run.id, "paused")
    assert "dispatched 12 times" in looping[0]["title"]
    assert looping[0]["url"].startswith("/chat?")

    run.status = "stopped"  # stopped manually by an operator
    await db.flush()
    cleared = await alerts.sweep(db, now=now + timedelta(minutes=1))

    assert cleared["cleared"] >= 1
    assert key in {item["key"] for item in await _deliveries(db, w["hook"], "problem.cleared")}
    assert key not in await alerts.open_alerts(db)
    trail = (await db.execute(select(AuditLog.action).where(AuditLog.resource_id == key)
                              .order_by(AuditLog.created_at))).scalars().all()
    assert trail == ["problems.raised", "problems.cleared"]


@pytest.mark.asyncio
async def test_a_burst_is_announced_up_to_the_cap_plus_one_summary_and_nothing_is_lost(db):
    w = await _world(db)
    now = utc_now()
    await alerts.sweep(db, now=now)
    runs = [_run(w, "paused", title=f"Run {n}", pause_reason="loop_limit", updated_at=now - timedelta(seconds=n))
            for n in range(alerts.MAX_ANNOUNCED_PER_SWEEP + 4)]
    db.add_all(runs)
    await db.flush()

    result = await alerts.sweep(db, now=now)

    assert (result["raised"], result["held"]) == (alerts.MAX_ANNOUNCED_PER_SWEEP, 4)
    raised = await _deliveries(db, w["hook"], "problem.raised")
    singles = [item for item in raised if item.get("reason_code") == "paused"]
    [summary] = [item for item in raised if item.get("reason_code") == "summary"]
    assert len(singles) == alerts.MAX_ANNOUNCED_PER_SWEEP
    assert summary["count"] == 4 and summary["title"].startswith("4 more problems")
    assert {f"run:{run.id}:paused" for run in runs} <= set(await alerts.open_alerts(db))


@pytest.mark.asyncio
async def test_attention_level_problems_are_not_announced(db):
    w = await _world(db)
    now = utc_now()
    await alerts.sweep(db, now=now)
    run = _run(w, title="Ticket delivery", updated_at=now - timedelta(minutes=25))  # silent 25 min: attention
    db.add(run)
    await db.flush()

    await alerts.sweep(db, now=now)

    assert f"run:{run.id}:silent" not in await alerts.open_alerts(db)
