"""Incremental work item syncs, one at a time per configuration (syncs are incremental so a
one-minute schedule works).

- **one run per configuration**: a run holds ``work_item_sync_configs.run_lease_until`` (an atomic conditional
  update, like the Knowledge source sync); another start meanwhile is recorded ``skipped: run_in_progress`` and a
  person's start is told so; a lease left by a crashed run expires after :data:`RUN_LEASE`;
- **incremental by default**: a run reads only what changed since the last successful run, with an overlap of
  :data:`OVERLAP_MINUTES`, in every status, so a closed or moved issue arrives. The window is relative
  (``updated >= -<n>m``), evaluated by the source against its own clock: no time zone or clock skew moves it;
- **a full run** (the whole filter, the only run that may conclude an item left it) on the first run, when a person
  asks for it (``full_resync``), and when the last full run is older than ``sync_options.full_resync_hours``
  (default :data:`FULL_RESYNC_HOURS`; 0 = only the first and manual ones).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItemSyncConfig, WorkItemSyncRun
from ...time_utils import utc_now

OVERLAP_MINUTES = 5
FULL_RESYNC_HOURS = 24
RUN_LEASE = timedelta(minutes=30)
MODE_FULL = "full"
MODE_INCREMENTAL = "incremental"
SKIPPED_RUN_IN_PROGRESS = "run_in_progress"
OK_STATUSES = ("completed",)


async def acquire_sync_lease(db: AsyncSession, config_id: str, *, now: datetime | None = None) -> bool:
    """Take the configuration's run lease; ``False`` while another run holds it. Commits."""
    now = now or utc_now()
    result = await db.execute(update(WorkItemSyncConfig).where(
        WorkItemSyncConfig.id == config_id,
        or_(WorkItemSyncConfig.run_lease_until.is_(None), WorkItemSyncConfig.run_lease_until < now),
    ).values(run_lease_until=now + RUN_LEASE).execution_options(synchronize_session=False))
    await db.commit()
    return result.rowcount == 1


async def release_sync_lease(db: AsyncSession, config_id: str) -> None:
    await db.execute(update(WorkItemSyncConfig).where(WorkItemSyncConfig.id == config_id)
                     .values(run_lease_until=None).execution_options(synchronize_session=False))


async def _last_ok(db: AsyncSession, config_id: str, *, full: bool) -> WorkItemSyncRun | None:
    rows = (await db.execute(select(WorkItemSyncRun).where(
        WorkItemSyncRun.sync_config_id == config_id, WorkItemSyncRun.status.in_(OK_STATUSES),
        WorkItemSyncRun.mode != "dry_run",
    ).order_by(WorkItemSyncRun.started_at.desc()).limit(200))).scalars().all()
    for row in rows:
        if not full or dict(row.summary_json or {}).get("window") != MODE_INCREMENTAL:
            return row
    return None


async def sync_window(db: AsyncSession, config: WorkItemSyncConfig, payload: dict[str, Any], *,
                      now: datetime | None = None) -> dict[str, Any]:
    """``{mode, minutes, reason}`` of the next run: ``minutes`` the incremental window including the overlap."""
    now = now or utc_now()
    if payload.get("full_resync") is True:
        return {"mode": MODE_FULL, "reason": "requested"}
    last = await _last_ok(db, config.id, full=False)
    if last is None:
        return {"mode": MODE_FULL, "reason": "first_run"}
    hours = dict(config.sync_options_json or {}).get("full_resync_hours", FULL_RESYNC_HOURS)
    hours = hours if type(hours) is int and hours >= 0 else FULL_RESYNC_HOURS
    if hours:
        full = await _last_ok(db, config.id, full=True)
        if full is None or now - full.started_at >= timedelta(hours=hours):
            return {"mode": MODE_FULL, "reason": "scheduled_full_resync"}
    minutes = max(1, math.ceil((now - last.started_at).total_seconds() / 60)) + OVERLAP_MINUTES
    return {"mode": MODE_INCREMENTAL, "minutes": minutes, "since_run": last.id}


def incremental_jql(filters: dict[str, Any], minutes: int) -> str:
    """The intake's query for the changes of the last ``minutes``, in every status (a built filter drops its status
    clause; the platform judges each returned issue against the whole filter)."""
    from .jira.jira_filters import build_jira_query_preview

    custom = str(filters.get("jql") or "").strip()
    base = custom or build_jira_query_preview({**filters, "statuses": None})
    upper = base.upper()
    if "ORDER BY" in upper:
        base = base[:upper.index("ORDER BY")].strip()
    window = f"updated >= -{minutes}m"
    return (f"({base}) AND {window}" if base else window) + " ORDER BY updated DESC"


__all__ = ["MODE_FULL", "MODE_INCREMENTAL", "OVERLAP_MINUTES", "RUN_LEASE", "SKIPPED_RUN_IN_PROGRESS",
           "acquire_sync_lease", "incremental_jql", "release_sync_lease", "sync_window"]
