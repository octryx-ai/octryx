"""Constants, health bookkeeping and small helpers shared by the connector watcher modules."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, ConnectorWatcher, ConnectorWatcherEvent, User
from ..connector_watcher_scope import WatcherScope, require_record
from ..secure_work.jira_values import object_value, parse_datetime

WATCHER_MODES = {"webhook", "polling", "hybrid"}
EVENT_STATUSES = {"received", "processed", "duplicate", "failed", "dead_letter", "rate_limited"}
DEFAULT_RETRY_POLICY = {"max_attempts": 3, "retry_delay_seconds": 60}
MAX_EVENTS = 500


def _retry_policy(value: Any) -> dict[str, int]:
    raw = object_value(value)
    max_attempts = _bounded_int(raw.get("max_attempts"), default=DEFAULT_RETRY_POLICY["max_attempts"], low=1, high=10)
    delay = _bounded_int(
        raw.get("retry_delay_seconds"),
        default=DEFAULT_RETRY_POLICY["retry_delay_seconds"],
        low=1,
        high=86400,
    )
    return {"max_attempts": max_attempts, "retry_delay_seconds": delay}


def _health(watcher: ConnectorWatcher, *, last_event: ConnectorWatcherEvent | None) -> dict[str, Any]:
    existing = object_value(watcher.health_json)
    return {
        **existing,
        "status": watcher.status,
        "last_event_id": last_event.id if last_event else watcher.last_event_id,
        "last_event_status": last_event.status if last_event else None,
        "last_event_at": _iso(last_event.received_at if last_event else watcher.last_event_at),
        "last_cursor": watcher.last_cursor,
        "dead_letter_count": watcher.dead_letter_count,
    }


def _increment_health(watcher: ConnectorWatcher, key: str, amount: int = 1) -> None:
    health = object_value(watcher.health_json)
    health[key] = int(health.get(key) or 0) + amount
    watcher.health_json = health


def _record_order_health(watcher: ConnectorWatcher, event: ConnectorWatcherEvent) -> None:
    if not event.occurred_at:
        return
    health = object_value(watcher.health_json)
    previous = parse_datetime(health.get("last_occurred_at"))
    if previous and event.occurred_at < previous:
        health["out_of_order_count"] = int(health.get("out_of_order_count") or 0) + 1
    if previous is None or event.occurred_at > previous:
        health["last_occurred_at"] = event.occurred_at.isoformat()
    watcher.health_json = health


WATCHER_NOT_FOUND = "Connector watcher not found"


async def _get_watcher(db: AsyncSession, watcher_id: str, *, scope: WatcherScope) -> ConnectorWatcher:
    return require_record(await db.get(ConnectorWatcher, watcher_id), scope, WATCHER_NOT_FOUND)


async def _get_active_watcher(db: AsyncSession, watcher_id: str, *, scope: WatcherScope) -> ConnectorWatcher:
    watcher = await _get_watcher(db, watcher_id, scope=scope)
    if not watcher.is_active:
        raise HTTPException(status_code=403, detail="Connector watcher is disabled")
    return watcher


async def _get_event(db: AsyncSession, event_id: str, *, scope: WatcherScope) -> ConnectorWatcherEvent:
    return require_record(await db.get(ConnectorWatcherEvent, event_id), scope, "Connector watcher event not found")


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _redact(value: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, current in value.items():
        lowered = key.lower()
        if any(marker in lowered for marker in ("token", "password", "secret", "credential", "api_key")):
            redacted[key] = "[redacted]"
        elif isinstance(current, dict):
            redacted[key] = _redact(current)
        elif isinstance(current, list):
            redacted[key] = [_redact(item) if isinstance(item, dict) else item for item in current]
        else:
            redacted[key] = current
    return redacted


def _public_webhook(row: ConnectorWatcher) -> dict[str, Any]:
    webhook = dict(row.webhook_json or {})
    webhook.pop("secret", None)
    webhook["secret_configured"] = bool(row.secret_ref)
    return webhook


def _audit(current_user: User, action: str, resource_id: str, details: dict[str, Any], *,
           project_id: str | None) -> AuditLog:
    return AuditLog(
        user_id=current_user.id,
        action=action,
        resource_type="connector_watcher",
        resource_id=resource_id,
        project_id=project_id,
        details=details,
    )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None
