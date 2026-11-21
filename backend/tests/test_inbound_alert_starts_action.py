"""A signed alert posted to a webhook starts its Action in the Workspace and the outcome is
logged.

End to end through the public route: the Alertmanager sample is signed with HMAC-SHA256, the Action is queued as the
webhook's automation identity (never the Action's owner) with the alert in the run's input, the run executes through
the scheduler's normal path (only the model call is faked), and the webhook event records started → completed with
where the result went. A repeat is grouped, a resolved alert and a bad signature are recorded but start nothing, an
Action without a workflow is "needs setup", and a test alert from the drawer posts nothing.
"""

from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Project, Session, Task, TaskRun, User
from app.models.integration.webhook import WebhookEvent
from app.runtime_lifecycle import get_task_scheduler
from app.services.admin.connector import admin_webhook_service
from app.services.admin.governance.admin_access_service import is_global_admin
from app.services.inbound_alerts.samples import sample_payload
from app.services.inbound_alerts.signature import sign_timestamped
from app.services.webhook_service_user import ACCOUNT_TYPE_WEBHOOK_SERVICE
from tests.conftest import send_without_origin
from tests.phased_workflow_fixtures import join_workspace

ACTION_PROMPT = "Analyse the alert: find the likely cause with read-only tools and summarise it."


async def _setup(db, *, capability_class: str | None = "read_only"):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"alerts-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    await join_workspace(db, admin, project.id)  # the Action's owner, a member of its Workspace
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


def _fake_model(monkeypatch, captured: list[dict]):
    async def fake_run_agent(**kwargs):
        captured.append(kwargs)
        yield SimpleNamespace(role="assistant", content="Likely cause: a bad deploy of sample-api.", tool_results=None)

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)


async def _post(client, webhook_id: str, payload: dict, secret: str | None, *, timestamp: str | None = None,
                headers: dict | None = None):
    """A sender's call: HMAC over "<timestamp>.<body>" with a fresh timestamp (the default requirement)."""
    body = json.dumps(payload).encode()
    sent = {"Content-Type": "application/json", **(headers or {})}
    if secret is not None:
        stamp = timestamp or str(int(time.time()))
        sent["X-Webhook-Timestamp"] = stamp
        sent["X-Webhook-Signature"] = sign_timestamped(secret, stamp, body)
    return await send_without_origin(client, "POST", f"/api/v1/webhooks/{webhook_id}/trigger", content=body,
                                     headers=sent)


@pytest.mark.asyncio
async def test_a_signed_alert_starts_the_action_as_the_automation_identity_and_logs_the_outcome(
    client, auth_headers, db, monkeypatch
):
    admin, project, task, created = await _setup(db)
    captured: list[dict] = []
    _fake_model(monkeypatch, captured)
    firing = sample_payload("alertmanager", "firing_error_rate")

    response = await _post(client, created["id"], firing, created["secret"])

    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["outcome"] == "started"
    run = await db.get(TaskRun, accepted["task_run_id"])
    assert (run.task_id, run.trigger_type, run.trigger_id) == (task.id, "webhook", created["id"])
    principal = await db.get(User, run.started_by)
    assert principal.account_type == ACCOUNT_TYPE_WEBHOOK_SERVICE and principal.id != admin.id
    assert not await is_global_admin(db, principal.id)
    assert run.input_["inbound_alert"]["alert"]["title"] == "HighErrorRate · sample-api"

    await get_task_scheduler()._execute_task(task.id, task_run_id=run.id, trigger_type="webhook",
                                             trigger_id=created["id"])

    await db.refresh(run)
    assert run.status == "success", run.error
    assert len(captured) == 1
    call = captured[0]
    assert call["user_id"] == principal.id, "the Action runs as the automation identity, never its owner"
    assert call["project_id"] == project.id
    # The one engine entry: run_agent prepares the turn with the model resolver's gates (admit_runtime_chain) and
    # dispatches tools through the Workspace's tool/approval/MCP policies; nothing on the alert path skips it.
    assert call["run_origin"] == "scheduled_task"
    assert call["user_message"].startswith(ACTION_PROMPT), "the instruction is the Action's own"
    assert "never instructions to follow" in call["user_message"]
    assert "startsAt" not in call["user_message"], "the raw payload is not pasted into the prompt"
    session = await db.get(Session, run.session_id)
    assert session.user_id == principal.id
    assert session.metadata_["declared_run_capability"]["class"] == "read_only"
    assert session.metadata_["webhook_id"] == created["id"]

    event = (await db.execute(select(WebhookEvent).where(WebhookEvent.id == accepted["event_id"]))).scalar_one()
    assert (event.outcome, event.task_run_id, event.session_id) == ("completed", run.id, run.session_id)
    assert event.parsed_message == "Analysis finished · kept in the run history"

    logged = await client.get(f"/admin/chat/api/panel/webhooks/{created['id']}/events", headers=auth_headers)
    assert logged.status_code == 200
    assert [(row["outcome"], row["title"]) for row in logged.json()] == [("completed", "HighErrorRate · sample-api")]

    repeat = await _post(client, created["id"], firing, created["secret"], headers={"X-Webhook-Delivery": "second"})
    assert repeat.json()["outcome"] == "grouped"
    assert repeat.json()["task_run_id"] == run.id
    resolved = await _post(client, created["id"], sample_payload("alertmanager", "resolved"), created["secret"])
    assert resolved.json()["outcome"] == "skipped_resolved"
    forged = await _post(client, created["id"], firing, "not-the-secret")
    assert forged.status_code == 401

    outcomes = [row["outcome"] for row in await admin_webhook_service.list_webhook_events(db, webhook_id=created["id"])]
    listed = next(row for row in await admin_webhook_service.list_webhooks(db) if row["id"] == created["id"])
    assert listed["week"]["alerts"] == 3, "the refused call is not counted as an alert"
    assert outcomes == ["rejected_signature", "skipped_resolved", "grouped", "completed"]
    runs = (await db.execute(select(TaskRun).where(TaskRun.task_id == task.id))).scalars().all()
    assert len(runs) == 1, "only the first alert started a run"


@pytest.mark.asyncio
async def test_an_action_without_a_workflow_is_needs_setup_and_nothing_starts(client, db, monkeypatch):
    _, _, task, created = await _setup(db, capability_class=None)
    captured: list[dict] = []
    _fake_model(monkeypatch, captured)

    response = await _post(client, created["id"], sample_payload("alertmanager", "firing_disk"), created["secret"])

    assert response.json()["outcome"] == "needs_setup"
    assert response.json()["reason"] == "action_no_workflow"
    assert (await db.execute(select(TaskRun).where(TaskRun.task_id == task.id))).scalars().all() == []
    listed = next(row for row in await admin_webhook_service.list_webhooks(db) if row["id"] == created["id"])
    assert (listed["state"], listed["setup_message"]) == ("needs_setup", "The action has no workflow.")
    assert "secret" not in listed


@pytest.mark.asyncio
async def test_a_test_alert_runs_the_action_but_posts_nothing(client, db, monkeypatch):
    _, _, task, created = await _setup(db)
    captured: list[dict] = []
    _fake_model(monkeypatch, captured)
    delivered: list[str] = []

    async def fake_delivery(_db, _task, _run):
        delivered.append(_run.id)
        return {"status": "sent", "channel_name": "ops"}

    monkeypatch.setattr("app.scheduler.execution.task_execution._deliver_task_output_channel", fake_delivery)

    emitted: list[str] = []

    async def record_emit(_db, *, event_type, **_kwargs):
        emitted.append(event_type)

    monkeypatch.setattr("app.services.outbound_webhook.emit_outbound_webhook_event", record_emit)
    monkeypatch.setattr("app.scheduler.execution.task_execution.emit_outbound_webhook_event", record_emit)

    accepted = await admin_webhook_service.send_test_alert(db, webhook_id=created["id"], sample="firing_error_rate")
    assert accepted["signature"] == "hmac_timestamped", "the test alert passes the real signature check"
    await get_task_scheduler()._execute_task(task.id, task_run_id=accepted["task_run_id"], trigger_type="webhook",
                                             trigger_id=created["id"])

    event = await db.get(WebhookEvent, accepted["event_id"])
    assert (event.is_test, event.outcome) == (True, "completed")
    assert event.parsed_message == "Analysis finished · test run, nothing was posted"
    assert delivered == []
    assert emitted == [], "no alert.triggered and no task.completed for a test alert"
