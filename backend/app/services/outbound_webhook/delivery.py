"""Outbound webhook deliveries: queue an event for every matching webhook, send due deliveries, retry."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import timedelta
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import OutboundWebhook, OutboundWebhookDelivery
from ...models.json_text import dump_json_dict
from ...time_utils import utc_now, utc_now_aware
from ..error_facts import error_text
from ..outbound_egress import CONNECTION_OUTBOUND_WEBHOOK, EgressRefusedError, egress_transport
from ..request_context import get_current_request_id
from ..secret import decrypt_secret
from .catalog import ALLOWED_OUTBOUND_WEBHOOK_EVENTS, OUTBOUND_WEBHOOK_RETRY_DELAYS_SECONDS
from .response_facts import response_facts_line


def _sign_payload(secret: str, *, timestamp: str, body: bytes) -> str:
    signature = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature}"


def _schedule_retry(
    row: OutboundWebhookDelivery,
    error: str,
    *,
    webhook: OutboundWebhook | None = None,
) -> None:
    row.retry_count = int(row.retry_count or 0) + 1
    row.error = (error or "").strip()[:4000] or "delivery_failed"
    if webhook is not None:
        webhook.last_delivery_status = "retrying"
        webhook.last_error = row.error
        webhook.last_delivery_at = utc_now()
    if row.retry_count > len(OUTBOUND_WEBHOOK_RETRY_DELAYS_SECONDS):
        row.status = "dead_letter"
        row.next_retry_at = None
        return
    delay = OUTBOUND_WEBHOOK_RETRY_DELAYS_SECONDS[row.retry_count - 1]
    row.status = "retrying"
    row.next_retry_at = utc_now() + timedelta(seconds=delay)


async def emit_outbound_webhook_event(
    db: AsyncSession,
    *,
    event_type: str,
    payload: dict[str, Any] | None = None,
    project_id: str | None = None,
    request_id: str | None = None,
) -> list[OutboundWebhookDelivery]:
    normalized_event = str(event_type or "").strip()
    if normalized_event not in ALLOWED_OUTBOUND_WEBHOOK_EVENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported outbound webhook event: {normalized_event}",
        )
    rows = (
        (
            await db.execute(
                select(OutboundWebhook).where(
                    OutboundWebhook.is_active,
                    or_(OutboundWebhook.project_id == project_id, OutboundWebhook.project_id.is_(None)),
                )
            )
        )
        .scalars()
        .all()
    )
    matching = [row for row in rows if normalized_event in row.event_types]
    if not matching:
        return []
    event_payload = payload if isinstance(payload, dict) else {}
    now = utc_now()
    created: list[OutboundWebhookDelivery] = []
    for row in matching:
        delivery = OutboundWebhookDelivery(
            id=str(uuid.uuid4()),
            webhook_id=row.id,
            project_id=project_id or row.project_id,
            event_type=normalized_event,
            payload_json=dump_json_dict(
                {
                    "event_type": normalized_event,
                    "project_id": project_id or row.project_id,
                    "emitted_at": now.isoformat(),
                    "payload": event_payload,
                }
            ),
            request_id=(request_id or get_current_request_id() or "").strip() or None,
            status="pending",
            retry_count=0,
            next_retry_at=now,
        )
        db.add(delivery)
        created.append(delivery)
    await db.flush()
    return created


def _delivery_headers(row: OutboundWebhookDelivery, secret: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(utc_now_aware().timestamp()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Octryx-OutboundWebhook/1.0",
        "X-Octryx-Event": row.event_type,
        "X-Octryx-Delivery-ID": row.id,
        "X-Octryx-Timestamp": timestamp,
        "X-Octryx-Signature": _sign_payload(secret, timestamp=timestamp, body=body),
    }
    if row.request_id:
        headers["X-Request-ID"] = row.request_id
    return headers


async def _post_delivery(
    row: OutboundWebhookDelivery,
    webhook: OutboundWebhook,
    *,
    body: bytes,
    headers: dict[str, str],
) -> None:
    try:
        # Egress-checked and pinned (SSRF guard); a redirect is a failed delivery, never followed.
        async with httpx.AsyncClient(
            timeout=20.0, follow_redirects=False, transport=egress_transport(CONNECTION_OUTBOUND_WEBHOOK)
        ) as client:
            response = await client.post(webhook.url, content=body, headers=headers)
        row.http_status = int(response.status_code)
        row.response_body = response_facts_line(response)
        if 200 <= response.status_code < 300:
            row.status = "sent"
            row.delivered_at = utc_now()
            row.next_retry_at = None
            row.error = None
            webhook.last_delivery_status = "sent"
            webhook.last_delivery_at = row.delivered_at
            webhook.last_error = None
        else:
            _schedule_retry(
                row,
                f"Unexpected HTTP status {response.status_code}",
                webhook=webhook,
            )
    except EgressRefusedError as refused:
        # A refused target does not become reachable by retrying.
        row.status = "dead_letter"
        row.next_retry_at = None
        row.error = f"egress_refused: {refused.reason}"
        webhook.last_delivery_status = "dead_letter"
        webhook.last_error = row.error
        webhook.last_delivery_at = utc_now()
    except Exception as exc:
        _schedule_retry(row, error_text("webhook_delivery_failed", exc), webhook=webhook)


async def _deliver(db: AsyncSession, row: OutboundWebhookDelivery) -> None:
    """Send one due delivery; a missing or inactive webhook dead-letters it, a failure schedules a retry."""
    webhook = await db.get(OutboundWebhook, row.webhook_id)
    if webhook is None or not webhook.is_active:
        row.status = "dead_letter"
        row.error = "Outbound webhook is missing or inactive"
        row.next_retry_at = None
        return
    try:
        secret = decrypt_secret(webhook.encrypted_secret)
    except Exception as exc:
        _schedule_retry(row, error_text("webhook_secret_decrypt_failed", exc), webhook=webhook)
        return
    body = row.payload_json.encode("utf-8")
    await _post_delivery(row, webhook, body=body, headers=_delivery_headers(row, secret, body))


async def process_outbound_webhook_delivery_batch(
    db: AsyncSession,
    *,
    batch_size: int = 20,
) -> int:
    now = utc_now()
    rows = (
        (
            await db.execute(
                select(OutboundWebhookDelivery)
                .where(
                    OutboundWebhookDelivery.status.in_(("pending", "retrying")),
                    or_(
                        OutboundWebhookDelivery.next_retry_at.is_(None),
                        OutboundWebhookDelivery.next_retry_at <= now,
                    ),
                )
                .order_by(OutboundWebhookDelivery.created_at.asc())
                .limit(max(1, min(batch_size, 100)))
            )
        )
        .scalars()
        .all()
    )
    processed = 0
    for row in rows:
        await _deliver(db, row)
        processed += 1
    if processed:
        await db.commit()
    return processed
