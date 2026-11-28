"""A signed alert posted to a webhook starts its Action as the webhook's automation identity, end to end through the
public route; repeats group, resolved alerts and bad signatures are recorded but start nothing."""

from __future__ import annotations

import json
import time
import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Task, TaskRun, User
from app.models.integration.webhook import WebhookEvent
from app.runtime_lifecycle import get_task_scheduler
from app.services.admin.connector import admin_webhook_service
from app.services.inbound_alerts.samples import sample_payload
from app.services.inbound_alerts.signature import sign_timestamped
from tests.conftest import send_without_origin
from tests.phased_workflow_fixtures import join_workspace
from tests.scripted_pool_support import (
    scripted_pool,  # noqa: F401 - fixture
    scripted_turns,  # noqa: F401 - fixture
)

pytestmark = [pytest.mark.usefixtures("scripted_turns"), pytest.mark.usefixtures("scripted_pool")]

ACTION_PROMPT = "Analyse the alert: find the likely cause with read-only tools and summarise it."


async def _setup(db, *, capability_class: str | None = "read_only"):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"alerts-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    await join_workspace(db, admin, project.id)
    config = {"prompt": ACTION_PROMPT}
    if capability_class:
        config["capability_class"] = capability_class
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Incident analysis", description="",
                task_type="agent_run", agent_type="diagnosis", owner_id=admin.id, is_active=True, config=config)
    db.add(task)
    await db.commit()
    created = await admin_webhook_service.create_webhook(
        db, user_id=admin.id,
        payload={"name": "Alertmanager", "project_id": project.id, "source_type": "alertmanager", "task_id": task.id},
    )
    return admin, project, task, created


async def _post(client, webhook_id: str, payload: dict, secret: str | None, *, timestamp: str | None = None,
                headers: dict | None = None):
    body = json.dumps(payload).encode()
    sent = {"Content-Type": "application/json", **(headers or {})}
    if secret is not None:
        stamp = timestamp or str(int(time.time()))
        sent["X-Webhook-Timestamp"] = stamp
        sent["X-Webhook-Signature"] = sign_timestamped(secret, stamp, body)
    return await send_without_origin(client, "POST", f"/api/v1/webhooks/{webhook_id}/trigger", content=body,
                                     headers=sent)


@pytest.mark.asyncio
async def test_an_action_without_a_workflow_is_needs_setup_and_nothing_starts(client, db, monkeypatch):
    admin, _, task, created = await _setup(db, capability_class=None)

    response = await _post(client, created["id"], sample_payload("alertmanager", "firing_disk"), created["secret"])

    assert response.json()["outcome"] == "needs_setup"
    assert response.json()["reason"] == "action_no_workflow"
    assert (await db.execute(select(TaskRun).where(TaskRun.task_id == task.id))).scalars().all() == []
    listed = next(row for row in await admin_webhook_service.list_webhooks(db, viewer_id=admin.id) if row["id"] == created["id"])
    assert (listed["state"], listed["setup_message"]) == ("needs_setup", "The action has no workflow.")
    assert "secret" not in listed


@pytest.mark.asyncio
async def test_a_test_alert_runs_the_action_but_posts_nothing(client, db, monkeypatch):
    admin, _, task, created = await _setup(db)
    delivered: list[str] = []

    async def fake_delivery(_db, _task, _run):
        delivered.append(_run.id)
        return {"status": "sent", "channel_name": "ops"}

    monkeypatch.setattr("app.scheduler.execution.task_run_finish._deliver_task_output_channel", fake_delivery)

    emitted: list[str] = []

    async def record_emit(_db, *, event_type, **_kwargs):
        emitted.append(event_type)

    monkeypatch.setattr("app.services.outbound_webhook.emit_outbound_webhook_event", record_emit)
    monkeypatch.setattr("app.scheduler.execution.task_run_finish.emit_outbound_webhook_event", record_emit)

    accepted = await admin_webhook_service.send_test_alert(db, webhook_id=created["id"], viewer_id=admin.id, sample="firing_error_rate")
    assert accepted["signature"] == "hmac_timestamped", "the test alert passes the real signature check"
    await get_task_scheduler()._execute_task(task.id, task_run_id=accepted["task_run_id"], trigger_type="webhook",
                                             trigger_id=created["id"])

    event = await db.get(WebhookEvent, accepted["event_id"])
    assert (event.is_test, event.outcome) == (True, "completed")
    assert event.parsed_message == "Analysis finished · test run, nothing was posted"
    assert delivered == []
    assert emitted == [], "no alert.triggered and no task.completed for a test alert"
