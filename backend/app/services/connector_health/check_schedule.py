"""When a connection is due for its next background check (automation V1)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorHealthLog
from ...time_utils import ensure_utc

HEALTH_CHECK_BASE_SECONDS = 300
HEALTH_CHECK_MAX_SECONDS = 3600
_FAILURE_LOOKBACK = 6


def next_check_delay_seconds(consecutive_failures: int) -> int:
    failures = max(0, int(consecutive_failures))
    return min(HEALTH_CHECK_MAX_SECONDS, HEALTH_CHECK_BASE_SECONDS * (2 ** min(failures, 8)))


def is_check_due(last_checked: datetime | None, consecutive_failures: int, now: datetime) -> bool:
    if last_checked is None:
        return True
    elapsed = (ensure_utc(now) - ensure_utc(last_checked)).total_seconds()
    return elapsed >= next_check_delay_seconds(consecutive_failures)


async def consecutive_failures(db: AsyncSession, connector_name: str, project_id: str | None = None) -> int:
    statuses = (
        await db.execute(
            select(ConnectorHealthLog.status)
            .where(
                ConnectorHealthLog.connector_name == connector_name,
                ConnectorHealthLog.project_id == str(project_id or ""),
            )
            .order_by(ConnectorHealthLog.checked_at.desc())
            .limit(_FAILURE_LOOKBACK)
        )
    ).scalars().all()
    count = 0
    for status in statuses:
        if status != "error":
            break
        count += 1
    return count


async def check_due(
    db: AsyncSession,
    *,
    connector_name: str,
    last_checked: datetime | None,
    now: datetime,
    project_id: str | None = None,
) -> bool:
    if last_checked is None:
        return True
    return is_check_due(last_checked, await consecutive_failures(db, connector_name, project_id), now)


def next_check_at(last_checked: datetime | None, consecutive_failures_count: int) -> datetime | None:
    if last_checked is None:
        return None
    return ensure_utc(last_checked) + timedelta(seconds=next_check_delay_seconds(consecutive_failures_count))


__all__ = [
    "HEALTH_CHECK_BASE_SECONDS",
    "HEALTH_CHECK_MAX_SECONDS",
    "check_due",
    "consecutive_failures",
    "is_check_due",
    "next_check_at",
    "next_check_delay_seconds",
]
