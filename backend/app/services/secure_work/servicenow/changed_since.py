"""Closures since the last successful sync: records changed at the source, even when they left the open set."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkItemSyncConfig
from ....time_utils import utc_now
from ...servicenow_scripted import normalize_record
from ..intake import closing
from ..intake.protocol import Changed
from .config import SOURCE_TYPE, is_closed
from .source import effective_limit, endpoint, reading, table_records, with_ref_ids

OVERLAP_MINUTES = 5
MAX_CHANGED = 2000
# Relative, evaluated by ServiceNow against its own clock: no time zone or clock skew moves the window
CHANGED_SINCE = "sys_updated_onRELATIVEGT@minute@ago@{minutes}"
COMPLETED = "completed"


def window_minutes(row: WorkItemSyncConfig, now: datetime | None = None) -> int | None:
    last = row.last_sync_at
    if last is None or row.last_sync_status != COMPLETED:
        return None
    now = now or utc_now()
    last = last.astimezone(UTC).replace(tzinfo=None) if last.tzinfo else last
    now = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
    return max(0, math.ceil((now - last).total_seconds() / 60)) + OVERLAP_MINUTES


async def changed_closed_records(config: Mapping[str, Any], intake: Mapping[str, Any], minutes: int | None,
                                 ) -> Changed:
    target = endpoint(config)
    if minutes is None or target.api is not None:
        return Changed(closed={}, minutes=None, complete=True)
    scope = effective_limit(config, intake)
    query = CHANGED_SINCE.format(minutes=minutes)
    closed: dict[str, dict[str, Any]] = {}
    complete = True
    async with reading(target) as client:
        for table in intake["tables"]:
            raw = await table_records(client, target.base_url, table, query, MAX_CHANGED + 1, target.headers, scope)
            complete = complete and len(raw) <= MAX_CHANGED
            for record in raw[:MAX_CHANGED]:
                normalized = normalize_record(with_ref_ids(record), table, target.base_url)
                sys_id = str(normalized.get("sys_id") or "").strip()
                if sys_id and is_closed(normalized.get("state"), intake):
                    closed[sys_id] = normalized
    return Changed(closed=closed, minutes=minutes, complete=complete)


async def close_changed(db: AsyncSession, *, row: WorkItemSyncConfig, instance: str, changed: Changed,
                        seen: set[str], user: User, dry_run: bool) -> int:
    return await closing.close_changed(db, row=row, instance=instance, changed=changed, seen=seen, user=user,
                                       dry_run=dry_run, source_type=SOURCE_TYPE, label="ServiceNow")


__all__ = [
    "CHANGED_SINCE",
    "MAX_CHANGED",
    "OVERLAP_MINUTES",
    "changed_closed_records",
    "close_changed",
    "window_minutes",
]
