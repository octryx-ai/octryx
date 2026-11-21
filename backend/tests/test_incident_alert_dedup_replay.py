"""An identical body again from an untimestamped Alertmanager sender is a resend, not an attack.

Alertmanager resends a group every ``repeat_interval`` with the same body and, with a Bearer token, no timestamp
and no delivery id. That repeat is answered 202 ``grouped`` when the dedup finds the same occurrence; every
other repeat stays a replay (409): a timestamped sender, a repeated delivery id, another source, or a repeat the
dedup would not group (it never starts anything).
"""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import select

from app.models import Project, Task
from app.models.integration.webhook import WebhookEvent
from app.runtime_lifecycle import get_task_scheduler
from app.services.admin.connector import admin_webhook_service
from app.services.inbound_alerts.samples import sample_payload
from app.services.inbound_alerts.signature import sign_body, sign_timestamped
from tests.conftest import send_without_origin
from tests.s5_alert_dedup_support import A, QueueOnly, am, task_runs  # noqa: F401
from tests.test_inbound_alert_starts_action import _setup


async def _untimestamped(db, monkeypatch, *, source_type: str = "alertmanager"):
    admin, project, task, created = await _setup(db)
    await admin_webhook_service.update_webhook(db, webhook_id=created["id"],
                                               payload={"accept_untimestamped": True, "source_type": source_type})
    monkeypatch.setattr(get_task_scheduler(), "run_task_now", QueueOnly(db).run_task_now)
    return project, task, created


async def _send(client, webhook_id: str, body: bytes, headers: dict):
    return await send_without_origin(client, "POST", f"/api/v1/webhooks/{webhook_id}/trigger", content=body,
                                     headers={"Content-Type": "application/json", **headers})


async def _outcomes(db, webhook_id: str) -> list[str]:
    rows = (await db.execute(select(WebhookEvent.outcome).where(WebhookEvent.webhook_id == webhook_id)
                             .order_by(WebhookEvent.received_at))).scalars().all()
    return list(rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", ["bearer", "hmac", "header"])
async def test_an_identical_alertmanager_resend_is_grouped_not_refused(client, db, monkeypatch, auth):
    _, task, created = await _untimestamped(db, monkeypatch)
    body = json.dumps(am(A)).encode()
    secret = created["secret"]
    headers = {"bearer": {"Authorization": f"Bearer {secret}"},
               "hmac": {"X-Webhook-Signature": sign_body(secret, body)},
               "header": {"X-Webhook-Secret": secret}}[auth]

    first = await _send(client, created["id"], body, headers)
    resend = await _send(client, created["id"], body, headers)

    assert first.status_code == 202 and first.json()["outcome"] == "started"
    assert resend.status_code == 202, resend.text
    assert (resend.json()["outcome"], resend.json()["dedup"]) == ("grouped", "same_occurrence")
    assert resend.json()["task_run_id"] == first.json()["task_run_id"]
    assert sorted(await _outcomes(db, created["id"])) == ["grouped", "started"]
    assert await task_runs(db, task.id) == 1


@pytest.mark.asyncio
async def test_a_timestamped_repeat_stays_a_replay(client, db, monkeypatch):
    _, task, created = await _untimestamped(db, monkeypatch)
    body = json.dumps(am(A)).encode()
    stamp = str(int(time.time()))
    headers = {"X-Webhook-Timestamp": stamp, "X-Webhook-Signature": sign_timestamped(created["secret"], stamp, body)}

    assert (await _send(client, created["id"], body, headers)).status_code == 202
    replay = await _send(client, created["id"], body, headers)

    assert replay.status_code == 409
    assert "rejected_replay" in await _outcomes(db, created["id"])
    assert await task_runs(db, task.id) == 1


@pytest.mark.asyncio
async def test_a_repeated_delivery_id_stays_a_replay(client, db, monkeypatch):
    _, _, created = await _untimestamped(db, monkeypatch)
    body = json.dumps(am(A)).encode()
    headers = {"Authorization": f"Bearer {created['secret']}", "X-Webhook-Delivery": "delivery-1"}

    assert (await _send(client, created["id"], body, headers)).status_code == 202
    assert (await _send(client, created["id"], body, headers)).status_code == 409


@pytest.mark.asyncio
async def test_another_source_s_identical_repeat_stays_a_replay(client, db, monkeypatch):
    _, _, created = await _untimestamped(db, monkeypatch, source_type="generic")
    body = json.dumps(sample_payload("generic", "firing_error_rate")).encode()
    headers = {"Authorization": f"Bearer {created['secret']}"}

    assert (await _send(client, created["id"], body, headers)).status_code == 202
    assert (await _send(client, created["id"], body, headers)).status_code == 409


@pytest.mark.asyncio
async def test_a_resend_the_dedup_would_not_group_is_refused_and_starts_nothing(client, db, monkeypatch):
    project, task, created = await _untimestamped(db, monkeypatch)
    action = await db.get(Task, task.id)
    action.config = {**action.config, "workflow_run": {"workflow_key": "incident-analysis", "alert_target": "required"}}
    await db.commit()
    body = json.dumps(am(A)).encode()
    headers = {"Authorization": f"Bearer {created['secret']}"}

    waiting = await _send(client, created["id"], body, headers)
    assert (waiting.status_code, waiting.json()["outcome"]) == (202, "needs_setup")
    workspace = await db.get(Project, project.id)
    workspace.config = {"alert_targets": [{"id": "checkout", "match": {"labels": {"service": "checkout"}}}]}
    await db.commit()

    resend = await _send(client, created["id"], body, headers)

    assert resend.status_code == 409, "a captured request never starts a run, even once the setup is fixed"
    assert await task_runs(db, task.id) == 0
