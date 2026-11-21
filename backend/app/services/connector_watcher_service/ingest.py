"""Ingesting webhook and polling events, listing them, and retrying failed ones."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorWatcherEvent, User
from ...time_utils import utc_now
from ..connector_watcher_polling import UnsupportedPollingTriggerError, ensure_api_ingestion_polling_trigger
from ..connector_watcher_scope import WatcherScope, scope_filter
from ..secure_work.jira_values import object_value
from .common import (
    MAX_EVENTS,
    _audit,
    _get_active_watcher,
    _get_event,
    _get_watcher,
    _health,
    _increment_health,
    _record_order_health,
    _retry_policy,
)
from .events import _mark_rate_limited_if_needed, _process_event, _record_event, _should_fail_on_retry
from .serialize import serialize_connector_watcher, serialize_watcher_event
from .watchers import _verify_webhook_secret


async def ingest_connector_webhook_event(
    db: AsyncSession,
    *,
    watcher_id: str,
    payload: dict[str, Any],
    provided_secret: str | None = None,
) -> dict[str, Any]:
    # The webhook is authenticated by the watcher's secret, not by a user: any Workspace's watcher answers.
    watcher = await _get_active_watcher(db, watcher_id, scope=None)
    if watcher.mode not in {"webhook", "hybrid"}:
        raise HTTPException(status_code=409, detail="Watcher does not accept webhook events")
    await _verify_webhook_secret(db, watcher, provided_secret)
    event = await _record_event(db, watcher, payload=payload, source="webhook")
    if event.status == "duplicate":
        _increment_health(watcher, "duplicate_count")
    elif await _mark_rate_limited_if_needed(db, watcher, event):
        _increment_health(watcher, "rate_limited_count")
    else:
        await _process_event(db, watcher=watcher, event=event)
    _record_order_health(watcher, event)
    watcher.health_json = _health(watcher, last_event=event)
    await db.flush()
    return serialize_watcher_event(event)


async def ingest_connector_poll_events(
    db: AsyncSession,
    *,
    watcher_id: str,
    current_user: User,
    scope: WatcherScope,
    payload: dict[str, Any],
) -> dict[str, Any]:
    watcher = await _get_active_watcher(db, watcher_id, scope=scope)
    if watcher.mode not in {"polling", "hybrid"}:
        raise HTTPException(status_code=409, detail="Watcher does not accept polling events")
    try:
        ensure_api_ingestion_polling_trigger(watcher.polling_json)
    except UnsupportedPollingTriggerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    recorded = []
    for item in events:
        event = await _record_event(db, watcher, payload=object_value(item), source="polling")
        if event.status == "duplicate":
            _increment_health(watcher, "duplicate_count")
        else:
            await _process_event(db, watcher=watcher, event=event)
        _record_order_health(watcher, event)
        recorded.append(event)
    cursor = object_value(payload.get("cursor"))
    if cursor:
        watcher.cursor_json = cursor
        watcher.last_cursor = json.dumps(cursor, sort_keys=True)
    watcher.updated_by = current_user.id
    db.add(_audit(current_user, "connector_watcher.poll_ingested", watcher.id, {"count": len(recorded)}))
    await db.flush()
    return {
        "watcher": serialize_connector_watcher(watcher),
        "items": [serialize_watcher_event(event) for event in recorded],
        "count": len(recorded),
    }


async def list_connector_watcher_events(
    db: AsyncSession,
    *,
    scope: WatcherScope,
    watcher_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(ConnectorWatcherEvent)
    condition = scope_filter(ConnectorWatcherEvent.project_id, scope, None)
    if condition is not None:
        stmt = stmt.where(condition)
    if watcher_id:
        stmt = stmt.where(ConnectorWatcherEvent.watcher_id == watcher_id)
    if status:
        stmt = stmt.where(ConnectorWatcherEvent.status == status)
    rows = (
        await db.execute(
            stmt.order_by(ConnectorWatcherEvent.received_at.desc()).limit(max(1, min(limit, MAX_EVENTS)))
        )
    ).scalars().all()
    return [serialize_watcher_event(row) for row in rows]


async def retry_connector_watcher_event(
    db: AsyncSession,
    *,
    event_id: str,
    current_user: User,
    scope: WatcherScope,
) -> dict[str, Any]:
    event = await _get_event(db, event_id, scope=scope)
    watcher = await _get_watcher(db, event.watcher_id, scope=scope)
    if event.status not in {"failed", "dead_letter"}:
        raise HTTPException(status_code=409, detail="Only failed or dead-letter events can be retried")
    event.attempts += 1
    _increment_health(watcher, "retry_count")
    _increment_health(watcher, "replay_count")
    retry_policy = _retry_policy(watcher.retry_policy_json)
    if _should_fail_on_retry(event):
        event.error = event.error or "Replay processing failure"
    else:
        event.status = "processed"
        event.error = None
        event.next_retry_at = None
        event.processing_result_json = {
            **dict(event.processing_result_json or {}),
            "replay": {"status": "processed", "attempt": event.attempts, "replayed_by": current_user.id},
        }
        await _process_event(db, watcher=watcher, event=event)
        watcher.status = "active"
        watcher.health_json = _health(watcher, last_event=event)
        db.add(_audit(current_user, "connector_watcher.event_replayed", event.id, {"status": event.status}))
        await db.flush()
        return serialize_watcher_event(event)
    if event.attempts >= retry_policy["max_attempts"]:
        event.status = "dead_letter"
        event.next_retry_at = None
        event.error = event.error or "Retry limit reached"
        watcher.dead_letter_count = int(watcher.dead_letter_count or 0) + 1
        _increment_health(watcher, "dead_letter_count")
    else:
        event.status = "failed"
        event.next_retry_at = utc_now() + timedelta(seconds=retry_policy["retry_delay_seconds"])
        _increment_health(watcher, "failure_count")
    watcher.status = "degraded" if event.status == "dead_letter" else "retry_pending"
    watcher.health_json = _health(watcher, last_event=event)
    db.add(_audit(current_user, "connector_watcher.event_retry", event.id, {"status": event.status}))
    await db.flush()
    return serialize_watcher_event(event)
