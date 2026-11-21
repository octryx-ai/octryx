"""Contract: a webhook delivery stores the receiver's status, body length and outcome, never the body (X6)."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.models import OutboundWebhookDelivery, User
from app.services.outbound_webhook import (
    create_outbound_webhook,
    emit_outbound_webhook_event,
    process_outbound_webhook_delivery_batch,
    serialize_outbound_webhook_delivery,
)

FAKE_TOKEN = ("ghp_X6" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123")
CREDENTIALED_URL = "https://user:tok3n@host/x.git"
INTERNAL_PATH = "/srv/internal/x6-secret-path"
RECEIVER_BODY = f"receiver-x6-says error at {INTERNAL_PATH}: use {CREDENTIALED_URL} with token {FAKE_TOKEN}"
MARKERS = (FAKE_TOKEN, "tok3n", CREDENTIALED_URL, INTERNAL_PATH, "receiver-x6-says")


def _assert_clean(value: object) -> None:
    serialized = json.dumps(value, default=str)
    for marker in MARKERS:
        assert marker not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(("status_code", "outcome", "status"), [(200, "accepted", "sent"), (500, "receiver_error", "retrying")])
async def test_delivery_keeps_status_length_and_outcome_only(db, monkeypatch, status_code, outcome, status):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await create_outbound_webhook(
        db,
        current_user=admin,
        payload={"name": "facts", "url": "https://example.test/hook", "event_types": ["task.completed"]},
    )
    await emit_outbound_webhook_event(db, event_type="task.completed", payload={"task_id": "t-1"})
    await db.commit()
    body = RECEIVER_BODY.encode("utf-8")

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, content=None, headers=None):
            return httpx.Response(status_code, content=body, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.outbound_webhook.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    assert await process_outbound_webhook_delivery_batch(db) == 1
    delivery = (await db.execute(select(OutboundWebhookDelivery))).scalar_one()
    await db.refresh(delivery)

    expected_line = f"outcome={outcome} http_status={status_code} content_length={len(body)}"
    assert delivery.status == status
    assert delivery.response_body == expected_line
    serialized = serialize_outbound_webhook_delivery(delivery)
    assert serialized["response_body"] == expected_line
    assert serialized["response_facts"] == {"outcome": outcome, "http_status": status_code, "content_length": len(body)}
    _assert_clean({"row": delivery.response_body, "error": delivery.error, "api": serialized})


@pytest.mark.asyncio
async def test_a_legacy_raw_response_body_is_never_serialized(db):
    legacy = OutboundWebhookDelivery(
        id="legacy-delivery",
        webhook_id="missing-hook",
        event_type="task.completed",
        status="sent",
        http_status=200,
        response_body=RECEIVER_BODY,
    )
    serialized = serialize_outbound_webhook_delivery(legacy)
    assert serialized["response_body"] is None
    assert serialized["response_facts"] is None
    _assert_clean(serialized)
