"""The platform's health checks (``/api/v1/health``, the API's readiness and liveness probe)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import exists, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ...models import ConnectorHealth, PlatformHealthCheck
from ...runtime_toggles import background_workers_enabled
from ...time_utils import utc_now
from ..redaction_policy import redact_secret_payload
from .health_worker_checks import STATUS_DISABLED, STATUS_UNKNOWN, WORKER_COMPONENTS, scheduler_checks, task_checks

logger = logging.getLogger(__name__)

DB_CHECK_SECONDS = 2.0
POOL_READ_SECONDS = 1.5
PERSIST_SECONDS = 10.0
# Tests store the results before the answer (one shared test connection must not be used by two tasks at once);
# the service stores them in the background so a busy pool never holds the probe.
PERSIST_INLINE = False
_probe_engine: AsyncEngine | None = None
_persisting: set[asyncio.Task] = set()


def _engine_for_probe(session_factory: async_sessionmaker[AsyncSession]) -> AsyncEngine | None:
    global _probe_engine
    bind = getattr(session_factory, "kw", {}).get("bind")
    url = getattr(bind, "url", None)
    if url is None or url.get_backend_name() == "sqlite":
        return None
    if _probe_engine is None or _probe_engine.url != url:
        _probe_engine = create_async_engine(url, poolclass=NullPool)
    return _probe_engine


async def _database_reachable(session_factory: async_sessionmaker[AsyncSession]) -> None:
    engine = _engine_for_probe(session_factory)
    if engine is None:
        async with session_factory() as db:
            await db.execute(text("SELECT 1"))
        return
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

CRITICAL_HEALTH_COMPONENTS = frozenset({"database", "scheduler", "task_queue_dispatcher"})


def _safe_health_error(value: object) -> str:
    redacted = redact_secret_payload({"error": str(value)})
    if isinstance(redacted, dict):
        return str(redacted.get("error") or "")
    return str(value)


def evaluate_platform_health_summary(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    error_components = sorted(
        component for component, payload in checks.items() if str(payload.get("status") or "") == "error"
    )
    degraded_components = sorted(
        component for component, payload in checks.items() if str(payload.get("status") or "") == "degraded"
    )
    # Unknown (never started, not checked) is not ok: it degrades the summary; disabled is a declared state.
    unknown_components = sorted(
        component for component, payload in checks.items() if str(payload.get("status") or "") == STATUS_UNKNOWN
    )
    critical_error_components = [component for component in error_components if component in CRITICAL_HEALTH_COMPONENTS]
    if critical_error_components:
        status = "error"
    elif error_components or degraded_components or unknown_components:
        status = "degraded"
    else:
        status = "ok"
    return {
        "status": status,
        "critical_components": sorted(CRITICAL_HEALTH_COMPONENTS),
        "critical_error_components": critical_error_components,
        "unknown_components": unknown_components,
        "error_components": error_components,
        "degraded_components": degraded_components,
    }


async def _database_check(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    db_started = time.perf_counter()
    db_status = "ok"
    db_error = None
    try:
        await asyncio.wait_for(_database_reachable(session_factory), DB_CHECK_SECONDS)
    except TimeoutError:
        db_status, db_error = "error", f"no answer within {DB_CHECK_SECONDS:g} s"
    except Exception as exc:
        db_status = "error"
        db_error = _safe_health_error(exc)
    return {
        "status": db_status,
        "response_time_ms": int((time.perf_counter() - db_started) * 1000),
        "error": db_error,
    }


async def _connector_health_check(
    session_factory: async_sessionmaker[AsyncSession], connector_health_worker: Any
) -> dict[str, Any]:
    connector_started = time.perf_counter()
    connector_task = getattr(connector_health_worker, "_task", None)
    connector_running = bool(connector_task is not None and not connector_task.done())
    connector_status = "ok"
    connector_error = None
    try:
        if await asyncio.wait_for(_any_connector_in_error(session_factory), POOL_READ_SECONDS):
            connector_status = "degraded"
            connector_error = "One or more connectors are unhealthy"
    except TimeoutError:
        connector_status, connector_error = "degraded", "the API's connection pool is busy"
    except Exception as exc:
        connector_status = "error"
        connector_error = _safe_health_error(exc)
    if not connector_running and connector_task is not None:
        connector_status = "error"
        connector_error = connector_error or "Connector health worker stopped unexpectedly"
    return {
        "status": connector_status,
        "response_time_ms": int((time.perf_counter() - connector_started) * 1000),
        "error": connector_error,
    }


async def run_platform_health_checks(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_scheduler: Any,
    channel_router: Any,
    retention_worker: Any,
    outbound_webhook_worker: Any,
    connector_health_worker: Any,
    analytics_worker: Any,
    worker_monitor_worker: Any,
    worker_agenda_worker: Any,
    worker_report_worker: Any,
    worker_pool_worker: Any,
    sla_monitor_worker: Any,
    secret_expiry_worker: Any,
    session_workspace_cleanup_worker: Any,
) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    workers_enabled = background_workers_enabled()
    checks["database"] = await _database_check(session_factory)

    if not workers_enabled:
        for component in WORKER_COMPONENTS:
            checks[component] = {"status": STATUS_DISABLED, "response_time_ms": 0, "error": "disabled"}
        await _store(session_factory, checks)
        return checks

    checks.update(scheduler_checks(task_scheduler))
    checks.update(task_checks((
        ("channel_router", channel_router),
        ("retention_worker", retention_worker),
        ("outbound_webhook_worker", outbound_webhook_worker),
    )))
    checks["connector_health_worker"] = await _connector_health_check(session_factory, connector_health_worker)
    checks.update(task_checks((
        ("analytics_worker", analytics_worker),
        ("worker_monitor_worker", worker_monitor_worker),
        ("worker_agenda_worker", worker_agenda_worker),
        ("worker_report_worker", worker_report_worker),
        ("worker_pool_worker", worker_pool_worker),
        ("sla_monitor_worker", sla_monitor_worker),
        ("secret_expiry_worker", secret_expiry_worker),
        ("session_workspace_cleanup_worker", session_workspace_cleanup_worker),
    )))

    await _store(session_factory, checks)
    return checks


async def _store(session_factory: async_sessionmaker[AsyncSession], checks: dict[str, dict[str, Any]]) -> None:
    _remember(checks)
    if PERSIST_INLINE:
        await _persist_platform_health_checks(session_factory, checks)
    else:
        _persist_later(session_factory, checks)


_last: tuple[float, dict[str, dict[str, Any]]] | None = None


def _remember(checks: dict[str, dict[str, Any]]) -> None:
    global _last
    _last = (time.time(), {component: dict(payload) for component, payload in checks.items()})


def last_platform_health_checks() -> tuple[float, dict[str, dict[str, Any]]] | None:
    return _last


def forget_platform_health_checks() -> None:
    global _last
    _last = None


async def _any_connector_in_error(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    # A platform total over every Workspace, whoever asks (the probe has no viewer): one yes or no, never a row.
    async with session_factory() as db:
        connection = await db.connection()
        return bool((await connection.execute(select(exists().where(
            ConnectorHealth.__table__.c.status == "error")))).scalar())


def _persist_later(session_factory: async_sessionmaker[AsyncSession], checks: dict[str, dict[str, Any]]) -> None:
    if any(not task.done() for task in _persisting):
        return
    task = asyncio.get_running_loop().create_task(
        asyncio.wait_for(_persist_platform_health_checks(session_factory, checks), PERSIST_SECONDS))
    _persisting.add(task)
    task.add_done_callback(_persisting.discard)
    task.add_done_callback(lambda done: done.cancelled() or done.exception())


async def _persist_platform_health_checks(
    session_factory: async_sessionmaker[AsyncSession],
    checks: dict[str, dict[str, Any]],
) -> None:
    if not checks:
        return
    now = utc_now()
    rows = [{"component": component, "status": payload["status"],
             "response_time_ms": int(payload["response_time_ms"]), "error": payload["error"], "checked_at": now}
            for component, payload in checks.items()]
    try:
        async with session_factory() as db:
            insert = postgresql_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
            statement = insert(PlatformHealthCheck).values(rows)
            await db.execute(statement.on_conflict_do_update(
                index_elements=[PlatformHealthCheck.component],
                set_={column: getattr(statement.excluded, column)
                      for column in ("status", "response_time_ms", "error", "checked_at")}))
            await db.commit()
    except Exception:
        logger.exception("Failed to persist platform health checks")
