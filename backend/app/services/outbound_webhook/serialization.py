"""Outbound webhooks and their deliveries as API payloads (receiver URLs masked)."""

from __future__ import annotations

from typing import Any

from ...models import OutboundWebhook, OutboundWebhookDelivery
from ...models.json_text import safe_json_dict
from ..redaction_policy import redact_embedded_credentials
from .response_facts import serialized_response_facts


def _mask_url(value: str) -> str:
    # Credentials in the URL first (a token as user name sat in the first 22 characters that stay visible).
    normalized = redact_embedded_credentials(str(value or "").strip())[0]
    if len(normalized) <= 28:
        return normalized
    return f"{normalized[:22]}...{normalized[-6:]}"


def serialize_outbound_webhook(row: OutboundWebhook) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "url": row.url,
        "url_masked": _mask_url(row.url),
        "event_types": row.event_types,
        "is_active": bool(row.is_active),
        "secret_configured": bool(row.secret_hash),
        "last_delivery_status": row.last_delivery_status,
        "last_delivery_at": row.last_delivery_at.isoformat() if row.last_delivery_at else None,
        "last_error": row.last_error,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_outbound_webhook_delivery(row: OutboundWebhookDelivery) -> dict[str, Any]:
    response_body, response_facts = serialized_response_facts(row.response_body)
    return {
        "id": row.id,
        "webhook_id": row.webhook_id,
        "project_id": row.project_id,
        "event_type": row.event_type,
        "payload": safe_json_dict(row.payload_json),
        "request_id": row.request_id,
        "status": row.status,
        "retry_count": int(row.retry_count or 0),
        "http_status": row.http_status,
        "response_body": response_body,
        "response_facts": response_facts,
        "error": row.error,
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
