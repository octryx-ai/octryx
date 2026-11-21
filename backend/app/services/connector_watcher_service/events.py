"""Recording, normalizing and processing one connector watcher event."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorWatcher, ConnectorWatcherEvent
from ...time_utils import utc_now
from ..connector_watcher_bitbucket import normalize_bitbucket_event
from ..connector_watcher_rules import evaluate_connector_watcher_rules_for_event
from ..connector_watcher_source_events import normalize_source_event
from ..engineering_knowledge import invalidate_engineering_knowledge_for_watcher_event
from ..secure_work.external_activity import link_connector_watcher_event_to_secure_work
from ..secure_work.jira_values import blank_to_none, object_value, parse_datetime
from .common import _bounded_int, _health, _increment_health, _payload_hash, _redact, _retry_policy


async def _process_event(db: AsyncSession, *, watcher: ConnectorWatcher, event: ConnectorWatcherEvent) -> None:
    if event.status in {"duplicate", "rate_limited"}:
        return
    await evaluate_connector_watcher_rules_for_event(db, watcher=watcher, event=event)
    await _link_event_to_secure_work(db, watcher=watcher, event=event)
    await _invalidate_engineering_knowledge_for_event(db, watcher=watcher, event=event)


async def _invalidate_engineering_knowledge_for_event(
    db: AsyncSession,
    *,
    watcher: ConnectorWatcher,
    event: ConnectorWatcherEvent,
) -> None:
    result = await invalidate_engineering_knowledge_for_watcher_event(
        db,
        watcher_event=event,
        actor_id=watcher.created_by,
    )
    if result.matched_count:
        event.processing_result_json = {
            **dict(event.processing_result_json or {}),
            "engineering_knowledge_lifecycle": result.as_dict(),
        }


async def _record_event(
    db: AsyncSession,
    watcher: ConnectorWatcher,
    *,
    payload: dict[str, Any],
    source: str,
) -> ConnectorWatcherEvent:
    normalized = _normalize_event(watcher, payload, source=source)
    duplicate = await _find_duplicate(db, watcher.id, normalized)
    status = "duplicate" if duplicate else "received"
    event = ConnectorWatcherEvent(
        watcher_id=watcher.id,
        project_id=watcher.project_id,
        connector_name=watcher.connector_name,
        connector_instance=watcher.connector_instance,
        provider_type=watcher.provider_type,
        duplicate_of_event_id=duplicate.id if duplicate else None,
        attempts=0,
        **normalized,
        status=status,
    )
    if payload.get("_simulate_processing_error") and not duplicate:
        _mark_failed(event, watcher)
    db.add(event)
    await db.flush()
    watcher.last_event_id = event.id
    watcher.last_event_at = event.received_at
    watcher.status = "degraded" if event.status == "dead_letter" else "active"
    if event.status == "failed":
        _increment_health(watcher, "failure_count")
    if event.status == "dead_letter":
        _increment_health(watcher, "dead_letter_count")
    watcher.health_json = _health(watcher, last_event=event)
    return event


async def _find_duplicate(
    db: AsyncSession,
    watcher_id: str,
    normalized: dict[str, Any],
) -> ConnectorWatcherEvent | None:
    external_id = normalized.get("external_id")
    event_type = normalized.get("event_type")
    payload_hash = normalized["payload_hash"]
    stmt = select(ConnectorWatcherEvent).where(ConnectorWatcherEvent.watcher_id == watcher_id)
    if external_id:
        stmt = stmt.where(
            or_(
                ConnectorWatcherEvent.payload_hash == payload_hash,
                (ConnectorWatcherEvent.event_type == event_type)
                & (ConnectorWatcherEvent.external_id == external_id),
            )
        )
    else:
        stmt = stmt.where(ConnectorWatcherEvent.payload_hash == payload_hash)
    return (await db.execute(stmt.order_by(ConnectorWatcherEvent.received_at.asc()))).scalars().first()


def _normalize_event(watcher: ConnectorWatcher, payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    event_type = str(payload.get("event_type") or payload.get("type") or "generic.event").strip()[:160]
    external_id = blank_to_none(payload.get("external_id") or payload.get("id") or payload.get("event_id"))
    actor = blank_to_none(payload.get("actor") or payload.get("user") or payload.get("author"))
    occurred_at = parse_datetime(payload.get("occurred_at") or payload.get("timestamp") or payload.get("created_at"))
    payload_hash = _payload_hash(payload)
    scope = object_value(payload.get("scope")) or dict(watcher.scope_json or {})
    raw_payload_ref = blank_to_none(payload.get("raw_payload_ref"))
    provider_normalized: dict[str, Any] = {}
    if watcher.provider_type == "bitbucket":
        provider_normalized = normalize_bitbucket_event(payload, watcher_scope=scope)
    elif watcher.provider_type in {"jira", "confluence", "knowledge"}:
        provider_normalized = normalize_source_event(payload, provider_type=watcher.provider_type, watcher_scope=scope)
    if provider_normalized:
        event_type = str(provider_normalized.get("event_type") or event_type).strip()[:160]
        external_id = blank_to_none(provider_normalized.get("external_id") or external_id)
        actor = blank_to_none(provider_normalized.get("actor") or actor)
        occurred_at = provider_normalized.get("occurred_at") or occurred_at
        scope = object_value(provider_normalized.get("scope")) or scope
    normalized_provider_payload = dict(provider_normalized.get("normalized") or {})
    if watcher.provider_type == "bitbucket" and normalized_provider_payload:
        normalized_provider_payload = {"bitbucket": normalized_provider_payload}
    return {
        "event_type": event_type or "generic.event",
        "external_id": external_id,
        "actor": actor,
        "occurred_at": occurred_at,
        "received_at": utc_now(),
        "payload_hash": payload_hash,
        "scope_json": scope,
        "raw_payload_ref": raw_payload_ref,
        "raw_payload_json": _redact(payload),
        "normalized_json": {
            "source": source,
            "provider": watcher.provider_type,
            "connector_name": watcher.connector_name,
            "connector_instance": watcher.connector_instance,
            "event_type": event_type,
            "external_id": external_id,
            "actor": actor,
            "scope": scope,
            **normalized_provider_payload,
        },
        "processing_result_json": {},
    }


async def _link_event_to_secure_work(
    db: AsyncSession,
    *,
    watcher: ConnectorWatcher,
    event: ConnectorWatcherEvent,
) -> None:
    if event.status == "duplicate":
        return
    links = await link_connector_watcher_event_to_secure_work(db, watcher=watcher, event=event)
    if links:
        event.processing_result_json = {
            **dict(event.processing_result_json or {}),
            "secure_work_links": links,
            "secure_work_link_count": len(links),
        }


async def _mark_rate_limited_if_needed(
    db: AsyncSession,
    watcher: ConnectorWatcher,
    event: ConnectorWatcherEvent,
) -> bool:
    limit = _webhook_rate_limit(watcher)
    if not limit:
        return False
    since = event.received_at - timedelta(seconds=60)
    count = (
        await db.execute(
            select(func.count(ConnectorWatcherEvent.id)).where(
                ConnectorWatcherEvent.watcher_id == watcher.id,
                ConnectorWatcherEvent.id != event.id,
                ConnectorWatcherEvent.received_at >= since,
                ConnectorWatcherEvent.status.notin_(["duplicate", "rate_limited"]),
            )
        )
    ).scalar_one()
    if int(count or 0) < limit:
        return False
    event.status = "rate_limited"
    event.error = "Watcher event storm protection rate limit exceeded"
    event.processing_result_json = {
        **dict(event.processing_result_json or {}),
        "rate_limited": True,
        "rate_limit": {"window_seconds": 60, "max_events": limit},
    }
    watcher.status = "throttled"
    return True


def _webhook_rate_limit(watcher: ConnectorWatcher) -> int | None:
    webhook = object_value(watcher.webhook_json)
    rate_limit = object_value(webhook.get("rate_limit"))
    value = rate_limit.get("max_events_per_minute") or webhook.get("max_events_per_minute")
    if value in (None, ""):
        return None
    return _bounded_int(value, default=0, low=0, high=100000) or None


def _mark_failed(event: ConnectorWatcherEvent, watcher: ConnectorWatcher) -> None:
    retry_policy = _retry_policy(watcher.retry_policy_json)
    event.attempts = 1
    event.error = "Simulated processing failure"
    if event.attempts >= retry_policy["max_attempts"]:
        event.status = "dead_letter"
        watcher.dead_letter_count = int(watcher.dead_letter_count or 0) + 1
    else:
        event.status = "failed"
        event.next_retry_at = utc_now() + timedelta(seconds=retry_policy["retry_delay_seconds"])


def _should_fail_on_retry(event: ConnectorWatcherEvent) -> bool:
    raw_payload = object_value(event.raw_payload_json)
    return bool(raw_payload.get("_simulate_processing_error") and not raw_payload.get("_simulate_retry_success"))
