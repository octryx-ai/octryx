"""Real health for managed databases.

A database's health is the result of the same probe as *Test connection* (``SELECT 1`` on a read-only connection),
stored in ``connector_health`` under the key ``database:<id>`` and checked by the connector health worker on
the shared schedule (5 min, backoff while failing). A database check never feeds a circuit
breaker: query tools fail closed on their own.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorHealth, DatabaseConnector

DATABASE_HEALTH_PREFIX = "database:"


def database_health_key(connector_id: str) -> str:
    return f"{DATABASE_HEALTH_PREFIX}{connector_id}"


async def record_database_health(db: AsyncSession, connector_id: str, result: dict[str, Any], duration_ms: int) -> dict:
    from ..connector_health.breaker_scope import check_status
    from ..connector_health.service import serialize_connector_health, upsert_connector_health

    status = check_status(result)
    summary = str(result.get("summary") or "").strip()
    details = str(result.get("details") or "").strip()
    row = await upsert_connector_health(
        db,
        connector_name=database_health_key(connector_id),
        project_id=None,
        status=status,
        response_time_ms=duration_ms,
        error=(summary or details) if status == "error" else "",
        details=details or summary,
    )
    return serialize_connector_health(row) or {}


async def check_database_health(db: AsyncSession, connector_id: str) -> dict:
    """Run the connection probe and store it as the database's current health."""
    return (await test_and_record_database(db, connector_id))["health"]


async def test_and_record_database(db: AsyncSession, connector_id: str) -> dict:
    """*Test connection*: the probe result plus the health it recorded (flushed; the caller commits)."""
    from ..database_tool_service import test_database_connector

    started = time.perf_counter()
    result = await test_database_connector(db, connector_id)
    health = await record_database_health(db, connector_id, result, int((time.perf_counter() - started) * 1000))
    return {**result, "health": health}


async def refresh_due_database_health(db: AsyncSession, *, now: datetime, force: bool = False) -> list[dict]:
    """Check every active database whose next check is due."""
    from ..connector_health.check_schedule import check_due

    connectors = (
        await db.execute(select(DatabaseConnector).where(DatabaseConnector.is_active.is_(True)))
    ).scalars().all()
    rows = await database_health_rows(db)
    results: list[dict] = []
    for connector in connectors:
        key = database_health_key(connector.id)
        current = rows.get(connector.id)
        if not force and not await check_due(
            db, connector_name=key, last_checked=current.last_checked if current else None, now=now
        ):
            continue
        results.append(await check_database_health(db, connector.id))
    return results


async def database_health_rows(db: AsyncSession) -> dict[str, ConnectorHealth]:
    query = select(ConnectorHealth).where(ConnectorHealth.connector_name.like(f"{DATABASE_HEALTH_PREFIX}%"))
    rows = (await db.execute(query)).scalars().all()
    return {row.connector_name[len(DATABASE_HEALTH_PREFIX):]: row for row in rows}


__all__ = [
    "DATABASE_HEALTH_PREFIX",
    "check_database_health",
    "database_health_key",
    "database_health_rows",
    "record_database_health",
    "refresh_due_database_health",
    "test_and_record_database",
]
