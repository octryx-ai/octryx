"""A Jira change source reads changes through the connection and starts the Action like an alert."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Project, Task, TaskRun, User
from app.models.integration.webhook import Webhook, WebhookEvent
from app.runtime_lifecycle import get_task_scheduler
from app.services.admin.connector import admin_webhook_service
from app.services.inbound_alerts.change_poller import poll_change_sources
from app.time_utils import utc_now


async def _change_source(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"changes-{uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.flush()
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Triage new P1", task_type="agent_run",
                owner_id=admin.id, is_active=True, config={"prompt": "Triage the issue.", "capability_class": "read_only"})
    db.add(task)
    await db.commit()
    created = await admin_webhook_service.create_webhook(db, user_id=admin.id, payload={
        "name": "New P1 issues", "project_id": project.id, "source_type": "jira_change", "task_id": task.id,
        "poll_query": "project = OPS AND priority = Highest"})
    return task, await db.get(Webhook, created["id"])


@pytest.mark.asyncio
async def test_a_changed_issue_starts_the_action_once_and_a_read_failure_is_logged(client, db):
    task, webhook = await _change_source(db)
    seen: list[tuple[str, object]] = []

    async def fake_jira(_db, hook, since, _limit):
        seen.append((hook.poll_query, since))
        return [{"key": "OPS-1", "summary": "Checkout fails", "status": "Open", "priority": "Highest",
                 "updated": "2026-01-01T10:00:00Z"}]

    now = utc_now()
    results = await poll_change_sources(db, now=now, scheduler=get_task_scheduler(), fetchers={"jira_change": fake_jira})

    assert [result["outcome"] for result in results] == ["started"]
    assert seen[0][0] == "project = OPS AND priority = Highest"
    run = await db.get(TaskRun, results[0]["task_run_id"])
    assert (run.task_id, run.trigger_type) == (task.id, "webhook")
    assert run.input_["inbound_alert"]["alert"]["title"] == "OPS-1 · Checkout fails"

    again = await poll_change_sources(db, now=now + timedelta(minutes=1), fetchers={"jira_change": fake_jira})
    assert again == [], "not due again within 5 minutes"
    repeat = await poll_change_sources(db, now=now + timedelta(minutes=6), scheduler=get_task_scheduler(),
                                       fetchers={"jira_change": fake_jira})
    assert repeat == [], "the same change (key + update time) is not handed over twice"

    async def broken(_db, _hook, _since, _limit):
        raise RuntimeError("jira_connection_not_configured")

    await poll_change_sources(db, now=now + timedelta(minutes=12), fetchers={"jira_change": broken})
    failed = (
        await db.execute(select(WebhookEvent).where(WebhookEvent.webhook_id == webhook.id,
                                                    WebhookEvent.alert_title == "Change check"))
    ).scalar_one()
    assert failed.outcome == "failed"
    assert failed.error == "change_read_failed:jira_connection_not_configured"


@pytest.mark.asyncio
async def test_more_changes_than_one_read_are_read_next_time_never_dropped(client, db):
    _task, webhook = await _change_source(db)
    now = utc_now()
    base = now - timedelta(minutes=4)
    changes = [
        {"key": f"OPS-{index}", "summary": "Change", "status": "Open", "priority": "Highest",
         "updated": (base + timedelta(seconds=index)).isoformat() + "Z",
         "_updated_utc": (base + timedelta(seconds=index)).isoformat()}
        for index in range(51)
    ]
    windows: list[object] = []

    async def fake_jira(_db, _hook, since, limit):
        windows.append(since)
        return [change for change in changes if datetime.fromisoformat(change["_updated_utc"]) >= since][:limit]

    first = await poll_change_sources(db, now=now, scheduler=get_task_scheduler(), fetchers={"jira_change": fake_jira})
    assert len(first) == 50
    await db.refresh(webhook)
    assert webhook.last_polled_at == base + timedelta(seconds=49), "the cursor stops at the last item read"

    second = await poll_change_sources(db, now=now + timedelta(minutes=2), scheduler=get_task_scheduler(),
                                       fetchers={"jira_change": fake_jira})
    assert len(second) == 1, "the 51st change is read next; the overlapping 50th is not handed over twice"
    titles = {event.alert_title for event in (
        await db.execute(select(WebhookEvent).where(WebhookEvent.webhook_id == webhook.id))).scalars()}
    assert len(titles) == 51, "every change is recorded (started or skipped by the hourly limit), none lost"
