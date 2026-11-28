"""Incremental work item syncs, one run at a time per configuration."""

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
    # ``False`` while another run holds the lease. Commits.
    now = now or utc_now()
    # An atomic conditional update: one run per configuration; a crashed run's lease expires after RUN_LEASE
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
    # Every status: a built filter drops its status clause, and the platform judges each returned issue against the
    # whole filter.
    from .jira.jira_filters import build_jira_query_preview

    custom = str(filters.get("jql") or "").strip()
    base = custom or build_jira_query_preview({**filters, "statuses": None})
    upper = base.upper()
    if "ORDER BY" in upper:
        base = base[:upper.index("ORDER BY")].strip()
    # Relative, evaluated by the source against its own clock: no time zone or clock skew moves the window
    window = f"updated >= -{minutes}m"
    return (f"({base}) AND {window}" if base else window) + " ORDER BY updated DESC"


__all__ = ["MODE_FULL", "MODE_INCREMENTAL", "OVERLAP_MINUTES", "RUN_LEASE", "SKIPPED_RUN_IN_PROGRESS",
           "acquire_sync_lease", "incremental_jql", "release_sync_lease", "sync_window"]
