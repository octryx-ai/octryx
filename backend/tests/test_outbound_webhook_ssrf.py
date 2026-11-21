"""Outbound webhooks go through the platform egress policy."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import OutboundWebhook, OutboundWebhookDelivery, User
from app.services.outbound_egress import PinnedEgressTransport
from app.services.outbound_webhook import (
    create_outbound_webhook,
    emit_outbound_webhook_event,
    process_outbound_webhook_delivery_batch,
    update_outbound_webhook,
)


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost/hook",
        "file:///etc/passwd",
    ],
)
async def test_create_refuses_a_loopback_metadata_or_non_http_receiver(db, url):
    with pytest.raises(HTTPException) as refused:
        await create_outbound_webhook(
            db,
            current_user=await _admin(db),
            payload={"name": "ssrf", "url": url, "event_types": ["task.completed"]},
        )

    assert refused.value.status_code == 400
    assert (await db.execute(select(OutboundWebhook).where(OutboundWebhook.name == "ssrf"))).first() is None


@pytest.mark.asyncio
async def test_update_refuses_a_metadata_receiver(db):
    created = await create_outbound_webhook(
        db,
        current_user=await _admin(db),
        payload={"name": "public", "url": "https://example.test/hook", "event_types": ["task.completed"]},
    )

    with pytest.raises(HTTPException) as refused:
        await update_outbound_webhook(db, webhook_id=created["id"], payload={"url": "http://169.254.169.254/"})

    assert refused.value.status_code == 400


@pytest.mark.asyncio
async def test_delivery_to_a_stored_private_url_is_refused_before_sending(db):
    created = await create_outbound_webhook(
        db,
        current_user=await _admin(db),
        payload={"name": "legacy", "url": "https://example.test/hook", "event_types": ["task.completed"]},
    )
    # A row stored with a URL the save-time guard would refuse.
    row = await db.get(OutboundWebhook, created["id"])
    row.url = "http://127.0.0.1:9/hook"
    await emit_outbound_webhook_event(db, event_type="task.completed", payload={"task_id": "t-1"})
    await db.commit()

    assert await process_outbound_webhook_delivery_batch(db) == 1

    delivery = (await db.execute(select(OutboundWebhookDelivery))).scalar_one()
    await db.refresh(delivery)
    assert delivery.status == "dead_letter"
    assert delivery.error.startswith("egress_refused:")
    assert delivery.http_status is None


@pytest.mark.asyncio
async def test_delivery_uses_the_pinned_egress_transport_without_redirects(db, monkeypatch):
    created = await create_outbound_webhook(
        db,
        current_user=await _admin(db),
        payload={"name": "pinned", "url": "https://example.test/hook", "event_types": ["task.completed"]},
    )
    await emit_outbound_webhook_event(db, event_type="task.completed", payload={})
    await db.commit()
    client_kwargs: dict[str, object] = {}

    class FakeResponse:
        status_code = 202
        text = "accepted"
        content = b"accepted"
        headers: dict[str, str] = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    def fake_client(*_args, **kwargs):
        client_kwargs.update(kwargs)
        return FakeClient()

    monkeypatch.setattr("app.services.outbound_webhook.httpx.AsyncClient", fake_client)

    await process_outbound_webhook_delivery_batch(db)

    assert client_kwargs["follow_redirects"] is False
    assert isinstance(client_kwargs["transport"], PinnedEgressTransport)
    assert created["id"]
