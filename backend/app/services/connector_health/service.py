from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...models import BuiltInToolConfig, ConnectorHealth, ConnectorHealthLog
from ...time_utils import ensure_utc, utc_now
from ..background_worker_state import (
    record_background_worker_failure,
    record_background_worker_success,
)
from ..secret import resolve_secret_refs
from ..tool_config import TOOL_CONFIG_PRESETS
from .breaker_scope import check_status, record_platform_check
from .check_schedule import check_due

logger = logging.getLogger(__name__)
# The worker wakes up every minute; each connection is checked only when due (check_schedule.py).
CONNECTOR_HEALTH_INTERVAL_SECONDS = 60
# The check history is diagnostic; one row per connector per minute grew without bound.
CONNECTOR_HEALTH_LOG_RETENTION_DAYS = 7


def _utc_iso(value) -> str | None:
    return ensure_utc(value).isoformat() if value else None


def serialize_connector_health(row: ConnectorHealth | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "connector_name": row.connector_name,
        "project_id": row.project_id or "",
        "status": row.status,
        "response_time_ms": int(row.response_time_ms) if row.response_time_ms is not None else None,
        "error": row.error or "",
        "details": row.details or "",
        "last_checked": _utc_iso(row.last_checked),
        "updated_at": _utc_iso(row.updated_at),
    }


def serialize_connector_health_log(row: ConnectorHealthLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "connector_name": row.connector_name,
        "project_id": row.project_id or "",
        "status": row.status,
        "response_time_ms": int(row.response_time_ms) if row.response_time_ms is not None else None,
        "error": row.error or "",
        "details": row.details or "",
        "checked_at": _utc_iso(row.checked_at),
    }


async def upsert_connector_health(
    db: AsyncSession,
    *,
    connector_name: str,
    project_id: str | None,
    status: str,
    response_time_ms: int | None,
    error: str | None,
    details: str | None,
) -> ConnectorHealth:
    normalized_project = str(project_id or "").strip()
    row = (
        await db.execute(
            select(ConnectorHealth).where(
                ConnectorHealth.connector_name == connector_name,
                ConnectorHealth.project_id == normalized_project,
            )
        )
    ).scalar_one_or_none()
    now = utc_now()
    if row is None:
        row = ConnectorHealth(connector_name=connector_name, project_id=normalized_project)
        db.add(row)
    row.status = status
    row.response_time_ms = response_time_ms
    row.error = (error or "").strip()[:2000] or None
    row.details = (details or "").strip()[:2000] or None
    row.last_checked = now
    row.updated_at = now
    db.add(
        ConnectorHealthLog(
            connector_name=connector_name,
            project_id=normalized_project,
            status=status,
            response_time_ms=response_time_ms,
            error=row.error,
            details=row.details,
            checked_at=now,
        )
    )
    await db.flush()
    return row


async def refresh_connector_health(
    db: AsyncSession,
    *,
    connector_name: str,
    config: dict[str, Any],
    run_connection_test,
    project_id: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = await run_connection_test(connector_name, config)
    duration_ms = int((time.perf_counter() - started) * 1000)
    summary = str(result.get("summary") or "").strip()
    details = str(result.get("details") or "").strip()
    status = check_status(result)
    row = await upsert_connector_health(
        db,
        connector_name=connector_name,
        project_id=project_id,
        status=status,
        response_time_ms=duration_ms,
        error="" if status != "error" else (summary or details),
        details=details if details else summary,
    )
    # Only the platform connection's check feeds its breaker; a Workspace check records health only.
    if not project_id:
        await record_platform_check(db, connector_name, status, summary or details)
    return serialize_connector_health(row) or {}


async def prune_connector_health_log(db: AsyncSession) -> int:
    """Delete check history older than the retention window; returns the number of rows removed."""
    cutoff = utc_now() - timedelta(days=CONNECTOR_HEALTH_LOG_RETENTION_DAYS)
    result = await db.execute(delete(ConnectorHealthLog).where(ConnectorHealthLog.checked_at < cutoff))
    return int(result.rowcount or 0)


async def list_connector_health_rows(db: AsyncSession) -> dict[tuple[str, str], ConnectorHealth]:
    rows = (await db.execute(select(ConnectorHealth))).scalars().all()
    return {(row.connector_name, row.project_id or ""): row for row in rows}


async def list_connector_health_log(
    db: AsyncSession,
    *,
    connector_name: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 100))
    rows = (
        (
            await db.execute(
                select(ConnectorHealthLog)
                .where(ConnectorHealthLog.connector_name == connector_name)
                .order_by(ConnectorHealthLog.checked_at.desc())
                .limit(safe_limit)
            )
        )
        .scalars()
        .all()
    )
    return [serialize_connector_health_log(row) for row in rows]


async def refresh_all_connector_health(
    db: AsyncSession,
    *,
    run_connection_test,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Check every active platform connection and managed database that is due (``force``: all)."""
    from ..database_tool.health import refresh_due_database_health

    now = utc_now()
    configs = (
        (await db.execute(select(BuiltInToolConfig).where(BuiltInToolConfig.project_id.is_(None)))).scalars().all()
    )
    current = await list_connector_health_rows(db)
    results: list[dict[str, Any]] = []
    for entry in configs:
        if entry.tool_name not in TOOL_CONFIG_PRESETS:
            continue
        if not bool(entry.is_active):
            continue
        row = current.get((entry.tool_name, ""))
        if not force and not await check_due(
            db, connector_name=entry.tool_name, last_checked=row.last_checked if row else None, now=now
        ):
            continue
        config = dict(entry.config or {})
        resolved = await resolve_secret_refs(db, config, tool_name=entry.tool_name, project_id=None,
                                             purpose="connector.health_check")
        health = await refresh_connector_health(
            db,
            connector_name=entry.tool_name,
            project_id=None,
            config=resolved,
            run_connection_test=run_connection_test,
        )
        results.append(health)
    results.extend(await refresh_due_database_health(db, now=now, force=force))
    await prune_connector_health_log(db)
    await db.commit()
    return results


class ConnectorHealthWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        run_connection_test,
        interval_seconds: int = CONNECTOR_HEALTH_INTERVAL_SECONDS,
    ):
        self._session_factory = session_factory
        self._run_connection_test = run_connection_test
        self._interval_seconds = max(5, int(interval_seconds))
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
        self._task = None

    async def run_once(self, *, force: bool = False) -> list[dict[str, Any]]:
        started_at = utc_now()
        try:
            async with self._session_factory() as db:
                result = await refresh_all_connector_health(
                    db, run_connection_test=self._run_connection_test, force=force
                )
            await record_background_worker_success(
                self._session_factory,
                worker_name="connector_health_worker",
                owner="connectors",
                started_at=started_at,
                result=result,
            )
            return result
        except Exception as exc:
            await record_background_worker_failure(
                self._session_factory,
                worker_name="connector_health_worker",
                owner="connectors",
                started_at=started_at,
                error=exc,
            )
            raise

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Connector health worker iteration failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue
