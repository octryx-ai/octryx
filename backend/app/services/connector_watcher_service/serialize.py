"""API views of connector watchers and their events."""

from __future__ import annotations

from typing import Any

from ...models import ConnectorWatcher, ConnectorWatcherEvent
from ..connector_watcher_polling import describe_connector_watcher_polling_contract
from .common import _iso, _public_webhook


def serialize_connector_watcher(row: ConnectorWatcher) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "connector_name": row.connector_name,
        "connector_instance": row.connector_instance,
        "provider_type": row.provider_type,
        "name": row.name,
        "description": row.description or "",
        "mode": row.mode,
        "event_types": list(row.event_types_json or []),
        "scope": dict(row.scope_json or {}),
        "polling": dict(row.polling_json or {}),
        "polling_contract": describe_connector_watcher_polling_contract(row.polling_json, mode=row.mode),
        "webhook": _public_webhook(row),
        "cursor": dict(row.cursor_json or {}),
        "retry_policy": dict(row.retry_policy_json or {}),
        "health": dict(row.health_json or {}),
        "status": row.status,
        "last_event_id": row.last_event_id,
        "last_event_at": _iso(row.last_event_at),
        "last_cursor": row.last_cursor,
        "dead_letter_count": row.dead_letter_count,
        "secret_configured": bool(row.secret_ref),
        "is_active": bool(row.is_active),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def serialize_watcher_event(row: ConnectorWatcherEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "watcher_id": row.watcher_id,
        "project_id": row.project_id,
        "connector_name": row.connector_name,
        "connector_instance": row.connector_instance,
        "provider_type": row.provider_type,
        "event_type": row.event_type,
        "external_id": row.external_id,
        "actor": row.actor,
        "occurred_at": _iso(row.occurred_at),
        "received_at": _iso(row.received_at),
        "payload_hash": row.payload_hash,
        "scope": dict(row.scope_json or {}),
        "raw_payload_ref": row.raw_payload_ref,
        "raw_payload": dict(row.raw_payload_json or {}),
        "normalized": dict(row.normalized_json or {}),
        "status": row.status,
        "duplicate_of_event_id": row.duplicate_of_event_id,
        "attempts": row.attempts,
        "next_retry_at": _iso(row.next_retry_at),
        "error": row.error,
        "processing_result": dict(row.processing_result_json or {}),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
