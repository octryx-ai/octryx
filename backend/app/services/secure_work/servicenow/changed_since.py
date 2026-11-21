"""Closures since the last successful sync: records changed at the source, even when they left the open set.

The open listing (``source.list_open_records``) reads ``active=true`` (or the intake's own narrowing query) on the
Table API, newest first and bounded by ``max_items``. A record closed at the source then drops out of it, and
``_close_left`` can only close its item when the listing was complete; a Workspace with more open records than
``max_items`` kept such items open forever.

So every Table API run also reads the records **changed since the last successful sync** with an overlap
(:data:`OVERLAP_MINUTES`), in any state: ``sys_updated_onRELATIVEGT@minute@ago@<n>`` inside the effective record
limit. The relative condition is evaluated by ServiceNow against its own clock, so neither the integration
user's time zone nor clock skew can move the window. Of those records only the ones in a closed state
(``excluded_states``) are used, and only to close an item **of this intake** (it never imports, so the intake's
own narrowing query needs no repetition here). The closed item takes the record's state as its
``source_status``. Without a successful sync yet there is no window and nothing is read. A Scripted REST listing
already carries every closed record of the endpoint, so this read applies to the Table API style only.

The window is bounded by :data:`MAX_CHANGED` records per table (``changed_complete`` reports a cut).
"""

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
CHANGED_SINCE = "sys_updated_onRELATIVEGT@minute@ago@{minutes}"
COMPLETED = "completed"


def window_minutes(row: WorkItemSyncConfig, now: datetime | None = None) -> int | None:
    """Minutes since the intake's last successful sync plus the overlap; ``None`` before the first one."""
    last = row.last_sync_at
    if last is None or row.last_sync_status != COMPLETED:
        return None
    now = now or utc_now()
    last = last.astimezone(UTC).replace(tzinfo=None) if last.tzinfo else last
    now = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
    return max(0, math.ceil((now - last).total_seconds() / 60)) + OVERLAP_MINUTES


async def changed_closed_records(config: Mapping[str, Any], intake: Mapping[str, Any], minutes: int | None,
                                 ) -> Changed:
    """The closed records of every configured table changed in the last ``minutes`` (Table API only)."""
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
    """``intake/closing.close_changed`` for a ServiceNow intake."""
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
