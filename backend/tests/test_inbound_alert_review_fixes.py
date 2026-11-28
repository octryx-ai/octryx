"""Retry identity, replay protection, refused-call log, error paths, API parity."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from app.models import TaskRun
from app.models.integration.webhook import Webhook, WebhookDeliveryKey, WebhookEvent
from app.runtime_lifecycle import get_task_scheduler
from app.services.admin.connector import admin_webhook_service
from app.services.inbound_alerts.samples import sample_payload
from app.services.inbound_alerts.signature import verify_call
from tests.conftest import send_without_origin
from tests.scripted_pool_support import (
    scripted_pool,  # noqa: F401 - fixture
    scripted_turns,  # noqa: F401 - fixture
)
from tests.test_inbound_alert_starts_action import _post, _setup

pytestmark = [pytest.mark.usefixtures("scripted_turns"), pytest.mark.usefixtures("scripted_pool")]

FIRING = sample_payload("alertmanager", "firing_error_rate")




@pytest.mark.asyncio
async def test_replays_stale_and_unsigned_timestamps_are_refused(client, db, monkeypatch):
    admin, _, _, created = await _setup(db)
    monkeypatch.setattr(get_task_scheduler(), "run_task_now",
                        lambda *a, **k: _queued())  # nothing runs; only the call guard is under test
    stamp = str(int(time.time()))
    assert (await _post(client, created["id"], FIRING, created["secret"], timestamp=stamp)).status_code == 202
    replay = await _post(client, created["id"], FIRING, created["secret"], timestamp=stamp)
    assert replay.status_code == 409, "the captured request starts nothing a second time"
    stale = await _post(client, created["id"], FIRING, created["secret"], timestamp=str(int(time.time()) - 600))
    assert stale.status_code == 401
    bearer = await send_without_origin(client, "POST", f"/api/v1/webhooks/{created['id']}/trigger", json=FIRING,
                                       headers={"Authorization": f"Bearer {created['secret']}"})
    assert bearer.status_code == 401, "no signed timestamp and the webhook does not accept that"

    await admin_webhook_service.update_webhook(db, webhook_id=created["id"], viewer_id=admin.id, payload={"accept_untimestamped": True})
    allowed = await send_without_origin(client, "POST", f"/api/v1/webhooks/{created['id']}/trigger",
                                        json=sample_payload("alertmanager", "firing_disk"),
                                        headers={"Authorization": f"Bearer {created['secret']}"})
    assert allowed.status_code == 202, "explicitly allowed for tools that cannot sign a timestamp"
    again = await send_without_origin(client, "POST", f"/api/v1/webhooks/{created['id']}/trigger",
                                      json=sample_payload("alertmanager", "firing_disk"),
                                      headers={"Authorization": f"Bearer {created['secret']}"})
    # Alertmanager's untimestamped resend of the same occurrence is grouped, not refused.
    assert again.status_code == 202, again.text
    assert (again.json()["outcome"], again.json()["dedup"]) == ("grouped", "same_occurrence")
    outcomes = {row["outcome"] for row in await admin_webhook_service.list_webhook_events(db, viewer_id=admin.id,
                                                                                    webhook_id=created["id"])}
    assert {"rejected_replay", "rejected_signature"} <= outcomes


async def _queued():
    return {"task_run_id": None}


@pytest.mark.asyncio
async def test_forged_calls_leave_one_counted_row_and_never_crash(client, db):
    _, _, _, created = await _setup(db)
    for _ in range(5):
        assert (await _post(client, created["id"], FIRING, "not-the-secret")).status_code == 401
    weird = await send_without_origin(client, "POST", f"/api/v1/webhooks/{created['id']}/trigger", json=FIRING,
                                      headers={"Authorization": "Bearer été".encode()})
    assert weird.status_code == 401, "a non-ASCII token is unequal, never a 500"
    rows = (await db.execute(select(WebhookEvent).where(WebhookEvent.webhook_id == created["id"]))).scalars().all()
    assert len(rows) == 1
    assert rows[0].raw_payload["count"] == 6
    assert verify_call({"Authorization": "Bearer é"}, b"{}", "secret", accept_untimestamped=True).ok is False


@pytest.mark.asyncio
async def test_a_paused_webhook_is_only_revealed_to_a_signed_caller(client, db):
    admin, _, _, created = await _setup(db)
    await admin_webhook_service.update_webhook(db, webhook_id=created["id"], viewer_id=admin.id, payload={"is_active": False})
    assert (await _post(client, created["id"], FIRING, "not-the-secret")).status_code == 401
    assert (await _post(client, created["id"], FIRING, created["secret"])).status_code == 403


@pytest.mark.asyncio
async def test_a_queue_failure_marks_the_event_failed_and_frees_the_delivery_key(client, db, monkeypatch):
    _, _, task, created = await _setup(db)

    async def broken(*_args, **_kwargs):
        raise RuntimeError("queue down")

    monkeypatch.setattr(get_task_scheduler(), "run_task_now", broken)
    response = await _post(client, created["id"], FIRING, created["secret"], headers={"X-Webhook-Delivery": "d-1"})
    assert response.status_code == 503
    event = (await db.execute(select(WebhookEvent).where(WebhookEvent.webhook_id == created["id"]))).scalar_one()
    assert (event.outcome, event.error, event.task_run_id) == ("failed", "action_not_queued", None)
    keys = (await db.execute(select(WebhookDeliveryKey).where(WebhookDeliveryKey.webhook_id == created["id"])))
    assert keys.scalars().all() == [], "the sender's retry is not taken for a replay"
    assert (await db.execute(select(TaskRun).where(TaskRun.task_id == task.id))).scalars().all() == []


@pytest.mark.asyncio
async def test_the_api_creates_a_webhook_with_its_action_and_no_agent_mode(client, auth_headers, db):
    _, project, task, _ = await _setup(db)
    response = await client.post("/api/v1/webhooks", headers=auth_headers, json={
        "project_id": project.id, "name": "api", "source_type": "alertmanager", "task_id": task.id,
        "rate_limit_per_hour": 5})
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["task_id"], body["rate_limit_per_hour"]) == (task.id, 5)
    assert "agent_type" not in body
    stored = await db.get(Webhook, body["id"])
    assert stored.task_id == task.id
    refused = await client.post("/api/v1/webhooks", headers=auth_headers, json={
        "project_id": project.id, "name": "api2", "rate_limit_per_hour": 0})
    assert refused.status_code == 422, "there is no unlimited"


