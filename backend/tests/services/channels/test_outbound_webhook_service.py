from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import OutboundWebhook, OutboundWebhookDelivery, Project, Session
from app.services.approval import ensure_approval_request
from app.services.outbound_webhook import (
    OUTBOUND_WEBHOOK_RETRY_DELAYS_SECONDS,
    create_outbound_webhook,
    emit_outbound_webhook_event,
    process_outbound_webhook_delivery_batch,
)
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_outbound_webhook_delivery_signs_and_sends(db, monkeypatch, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    created = await create_outbound_webhook(
        db,
        current_user=auth_user,
        payload={
            "name": "task events",
            "url": "https://example.test/hook",
            "project_id": project.id,
            "event_types": ["task.completed"],
        },
    )
    secret = created["signing_secret"]
    assert secret

    await emit_outbound_webhook_event(
        db,
        event_type="task.completed",
        project_id=project.id,
        request_id="req-outbound-1",
        payload={"task_id": "task-1", "status": "success"},
    )
    await db.commit()

    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 202
        text = "accepted"
        content = b"accepted"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, content=None, headers=None):
            captured["url"] = url
            captured["content"] = content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else content
            captured["headers"] = dict(headers or {})
            return FakeResponse()

    monkeypatch.setattr("app.services.outbound_webhook.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    processed = await process_outbound_webhook_delivery_batch(db)
    assert processed == 1

    delivery = (await db.execute(select(OutboundWebhookDelivery))).scalar_one()
    await db.refresh(delivery)
    webhook = await db.get(OutboundWebhook, created["id"])
    assert delivery.status == "sent"
    assert delivery.http_status == 202
    assert delivery.request_id == "req-outbound-1"
    assert webhook.last_delivery_status == "sent"
    assert captured["url"] == "https://example.test/hook"
    assert '"event_type": "task.completed"' in str(captured["content"])
    headers = captured["headers"]
    assert headers["X-Octryx-Event"] == "task.completed"
    assert headers["X-Octryx-Delivery-ID"] == delivery.id
    assert headers["X-Request-ID"] == "req-outbound-1"
    assert str(headers["X-Octryx-Signature"]).startswith("sha256=")


@pytest.mark.asyncio
async def test_outbound_webhook_retries_and_dead_letters(db, monkeypatch, auth_user):
    created = await create_outbound_webhook(
        db,
        current_user=auth_user,
        payload={
            "name": "failing",
            "url": "https://example.test/fail",
            "event_types": ["task.failed"],
        },
    )

    await emit_outbound_webhook_event(
        db,
        event_type="task.failed",
        request_id="req-outbound-retry",
        payload={"task_id": "task-2", "status": "error"},
    )
    await db.commit()

    class FakeResponse:
        status_code = 503
        text = "temporary outage"
        content = b"temporary outage"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, content=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr("app.services.outbound_webhook.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    delivery = (await db.execute(select(OutboundWebhookDelivery))).scalar_one()
    for _ in range(len(OUTBOUND_WEBHOOK_RETRY_DELAYS_SECONDS) + 1):
        processed = await process_outbound_webhook_delivery_batch(db)
        assert processed == 1
        await db.refresh(delivery)
        if delivery.status == "dead_letter":
            break
        delivery.next_retry_at = utc_now()
        await db.commit()

    assert delivery.status == "dead_letter"
    assert delivery.retry_count == len(OUTBOUND_WEBHOOK_RETRY_DELAYS_SECONDS) + 1
    assert delivery.http_status == 503
    assert "Unexpected HTTP status 503" in (delivery.error or "")
    webhook = await db.get(OutboundWebhook, created["id"])
    assert webhook.last_delivery_status == "retrying"


@pytest.mark.asyncio
async def test_approval_hook_enqueues_outbound_deliveries(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    await create_outbound_webhook(
        db,
        current_user=auth_user,
        payload={
            "name": "approval",
            "url": "https://example.test/events",
            "project_id": project.id,
            "event_types": ["approval.requested"],
        },
    )

    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
    )
    db.add(session)
    await db.commit()

    approval = await ensure_approval_request(
        db,
        requested_by=auth_user.id,
        action="Approve command execution for bash",
        reason="Command: terraform plan",
        session_id=session.id,
    )
    await db.commit()

    deliveries = (
        (
            await db.execute(
                select(OutboundWebhookDelivery).where(OutboundWebhookDelivery.event_type == "approval.requested")
            )
        )
        .scalars()
        .all()
    )
    assert deliveries
    assert any((delivery.payload_json or "").find(approval.id) >= 0 for delivery in deliveries)
