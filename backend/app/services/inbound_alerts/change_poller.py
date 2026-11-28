"""Jira and ServiceNow changes as an inbound source (automation V7; replaces the inert watcher rules)."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...models.integration.webhook import Webhook, WebhookEvent
from ...time_utils import utc_now
from .call_guard import claim_delivery_key
from .normalize import POLLED_SOURCE_TYPES, normalize_alert
from .trigger import receive_alert

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300
POLL_MAX_ITEMS = 50
STATE_POLL_FAILED = "change_read_failed"

# (db, webhook, since, limit) -> changes oldest first, each with ``_updated_utc`` (naive-UTC ISO).
ChangeFetcher = Callable[[AsyncSession, Webhook, datetime, int], Awaitable[list[dict[str, Any]]]]


def _window_minutes(since: datetime) -> int:
    return max(1, math.ceil((utc_now() - since).total_seconds() / 60) + 1)


def _utc_iso(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed.isoformat()


async def fetch_jira_changes(
    db: AsyncSession, webhook: Webhook, since: datetime, limit: int
) -> list[dict[str, Any]]:
    from ...models import WorkItemSyncConfig
    from ..secure_work.jira.jira_connector import fetch_jira_issues_for_sync

    query = (webhook.poll_query or "").strip()
    # Relative window: Jira reads absolute dates in the account's time zone, minutes back are unambiguous.
    window = f"updated >= -{_window_minutes(since)}m"
    jql = f"({query}) AND {window} ORDER BY updated ASC" if query else f"{window} ORDER BY updated ASC"
    # A transient intake-shaped config: the Workspace's default Jira connection, never persisted.
    config = WorkItemSyncConfig(project_id=webhook.project_id, connection_id="default", source_type="jira",
                                sync_options_json={}, field_mapping_json={})
    found = await fetch_jira_issues_for_sync(db, config=config, jql=jql, limit=limit)
    if not found.get("configured"):
        raise RuntimeError("jira_connection_not_configured")
    changes = []
    for issue in found.get("issues") or []:
        fields = issue.get("fields") or {}
        status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
        priority = fields.get("priority") if isinstance(fields.get("priority"), dict) else {}
        changes.append({
            "key": issue.get("key"), "summary": fields.get("summary"), "status": status.get("name"),
            "priority": priority.get("name"), "updated": fields.get("updated"),
            "_updated_utc": _utc_iso(fields.get("updated")),
        })
    return changes


async def fetch_servicenow_changes(
    db: AsyncSession, webhook: Webhook, since: datetime, limit: int
) -> list[dict[str, Any]]:
    from ..secure_work.intake.connections import connection_config_of
    from ..secure_work.servicenow.source import endpoint, reading

    config = await connection_config_of(db, webhook.project_id, "servicenow", None)
    if not config:
        raise RuntimeError("servicenow_connection_not_configured")
    target = endpoint(config)
    # Relative window and raw (UTC) values: no dependence on the integration user's time zone.
    window = f"sys_updated_onRELATIVEGT@minute@ago@{_window_minutes(since)}"
    query = "^".join(part for part in ((webhook.poll_query or "").strip(), window, "ORDERBYsys_updated_on") if part)
    async with reading(target) as client:
        response = await client.get(
            f"{target.base_url}/api/now/table/incident",
            params={"sysparm_query": query, "sysparm_display_value": "false", "sysparm_limit": limit,
                    "sysparm_exclude_reference_link": "true",
                    "sysparm_fields": "number,short_description,state,priority,sys_updated_on"},
            headers=target.headers,
        )
    if response.status_code != 200:
        raise RuntimeError("servicenow_read_failed")
    records = (response.json() or {}).get("result") or []
    return [
        {**{key: record.get(key) for key in ("number", "short_description", "state", "priority", "sys_updated_on")},
         "_updated_utc": _utc_iso(record.get("sys_updated_on"))}
        for record in records if isinstance(record, dict)
    ]


CHANGE_FETCHERS: dict[str, ChangeFetcher] = {
    "jira_change": fetch_jira_changes,
    "servicenow_change": fetch_servicenow_changes,
}


def _next_cursor(changes: list[dict[str, Any]], *, since: datetime, current: datetime) -> datetime:
    if len(changes) < POLL_MAX_ITEMS:
        return current
    last = changes[-1].get("_updated_utc")
    try:
        cursor = datetime.fromisoformat(str(last)) if last else None
    except ValueError:
        cursor = None
    return cursor if cursor is not None and cursor > since else current


def _due(webhook: Webhook, now: datetime) -> bool:
    return webhook.last_polled_at is None or (now - webhook.last_polled_at).total_seconds() >= POLL_INTERVAL_SECONDS


async def poll_change_sources(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    scheduler: Any = None,
    fetchers: dict[str, ChangeFetcher] | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    current = now or utc_now()
    readers = fetchers or CHANGE_FETCHERS
    webhooks = (
        await db.execute(
            select(Webhook).where(Webhook.is_active.is_(True), Webhook.source_type.in_(sorted(POLLED_SOURCE_TYPES)))
        )
    ).scalars().all()
    results: list[dict[str, Any]] = []
    for webhook in webhooks:
        if not force and not _due(webhook, current):
            continue
        since = webhook.last_polled_at or (current - timedelta(seconds=POLL_INTERVAL_SECONDS))
        webhook_id = webhook.id
        try:
            changes = await readers[webhook.source_type](db, webhook, since, POLL_MAX_ITEMS)
        except Exception as exc:
            logger.warning("inbound_alert.poll_failed webhook_id=%s", webhook_id, exc_info=True)
            reason = str(exc) if str(exc).isidentifier() else type(exc).__name__
            db.add(WebhookEvent(webhook_id=webhook_id, status="failed", outcome="failed", alert_title="Change check",
                                parsed_message="Could not read the changes; checked again in 5 minutes",
                                error=f"{STATE_POLL_FAILED}:{reason}"[:500], processed_at=current))
            webhook.last_polled_at = current
            await db.commit()
            continue
        for change in changes:
            alert_payload = {key: value for key, value in change.items() if not key.startswith("_")}
            fingerprint = normalize_alert(webhook.source_type, alert_payload).fingerprint
            # The window overlaps by a minute (and a full batch is re-read from its last item): an item already
            # handed over is not handed over again.
            if not await claim_delivery_key(db, webhook_id, f"poll:{fingerprint}"):
                continue
            results.append(await receive_alert(db, webhook=webhook, body=b"", payload=alert_payload, verified=True,
                                               scheduler=scheduler))
        webhook.last_polled_at = _next_cursor(changes, since=since, current=current)
        if len(changes) >= POLL_MAX_ITEMS and webhook.last_polled_at == current:
            db.add(WebhookEvent(webhook_id=webhook_id, status="skipped", outcome="failed", alert_title="Change check",
                                parsed_message=f"More than {POLL_MAX_ITEMS} changes share one update time; "
                                               "the rest could not be read",
                                error=f"{STATE_POLL_FAILED}:batch_not_advancing", processed_at=current))
        await db.commit()
    return results


class ChangeSourcePollWorker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, tick_seconds: int = 60) -> None:
        self._session_factory = session_factory
        self._tick = max(5, int(tick_seconds))
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
        self._task = None

    async def run_once(self) -> list[dict[str, Any]]:
        async with self._session_factory() as db:
            return await poll_change_sources(db)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Change source poll iteration failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick)
            except TimeoutError:
                continue


__all__ = [
    "CHANGE_FETCHERS",
    "POLL_INTERVAL_SECONDS",
    "ChangeSourcePollWorker",
    "fetch_jira_changes",
    "fetch_servicenow_changes",
    "poll_change_sources",
]
