from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.runtime_toggles import DISABLE_BACKGROUND_WORKERS_ENV
from app.services.observability.health_checks import evaluate_platform_health_summary, run_platform_health_checks


@pytest.mark.asyncio
async def test_platform_health_marks_disabled_workers_disabled_not_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv(DISABLE_BACKGROUND_WORKERS_ENV, "1")
    # An own database file under pytest's tmp_path (cleaned by pytest), not the shared test database.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'observability_health.db'}", echo=False,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    checks = await run_platform_health_checks(
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        task_scheduler=None,
        channel_router=None,
        retention_worker=None,
        outbound_webhook_worker=None,
        connector_health_worker=None,
        analytics_worker=None,
        prefetch_worker=None,
        worker_monitor_worker=None,
        worker_agenda_worker=None,
        worker_report_worker=None,
        worker_pool_worker=None,
        sla_monitor_worker=None,
        secret_expiry_worker=None,
        session_workspace_cleanup_worker=None,
    )

    assert checks["database"]["status"] == "ok"
    # Observability O4: disabled is its own state, never "ok"; it does not degrade the summary.
    assert checks["scheduler"] == {"status": "disabled", "response_time_ms": 0, "error": "disabled"}
    assert checks["task_queue_dispatcher"] == {
        "status": "disabled",
        "response_time_ms": 0,
        "error": "disabled",
    }
    assert {name: check["status"] for name, check in checks.items() if name != "database"} == dict.fromkeys(
        (name for name in checks if name != "database"), "disabled")
    assert evaluate_platform_health_summary(checks)["status"] == "ok"
    await engine.dispose()


def test_a_worker_that_never_started_is_unknown_and_degrades_the_summary() -> None:
    from types import SimpleNamespace

    from app.services.observability.health_worker_checks import _task_component_check

    check = _task_component_check(worker=SimpleNamespace(_task=None), stopped_message="stopped")
    assert (check["status"], check["error"]) == ("unknown", "not started")
    summary = evaluate_platform_health_summary({"database": {"status": "ok"}, "retention_worker": check})
    assert summary["status"] == "degraded" and summary["unknown_components"] == ["retention_worker"]


def test_platform_health_summary_marks_critical_errors_as_error() -> None:
    summary = evaluate_platform_health_summary(
        {
            "database": {"status": "error", "response_time_ms": 1, "error": "connection failed"},
            "connector_health_worker": {"status": "degraded", "response_time_ms": 1, "error": "unhealthy"},
        }
    )

    assert summary["status"] == "error"
    assert summary["critical_error_components"] == ["database"]
    assert summary["error_components"] == ["database"]
    assert summary["degraded_components"] == ["connector_health_worker"]


def test_platform_health_summary_marks_non_critical_errors_as_degraded() -> None:
    summary = evaluate_platform_health_summary(
        {
            "database": {"status": "ok", "response_time_ms": 1, "error": None},
            "connector_health_worker": {"status": "error", "response_time_ms": 1, "error": "unhealthy"},
        }
    )

    assert summary["status"] == "degraded"
    assert summary["critical_error_components"] == []
    assert summary["error_components"] == ["connector_health_worker"]


@pytest.mark.asyncio
async def test_a_busy_connection_pool_never_holds_the_probe(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """An exhausted pool (5 + 10) must not make the probe wait for it, time out after 5 s and take the API out of
    service. The database is checked over its own connection, the connector read is bounded, the results are
    stored afterwards."""
    import asyncio
    import time

    from app.services.observability import health_checks

    monkeypatch.setenv(DISABLE_BACKGROUND_WORKERS_ENV, "1")
    probe = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'probe.db'}")
    monkeypatch.setattr(health_checks, "_engine_for_probe", lambda _factory: probe)
    monkeypatch.setattr(health_checks, "PERSIST_SECONDS", 0.2)
    monkeypatch.setattr(health_checks, "PERSIST_INLINE", False)  # the service's way: stored in the background

    class _Exhausted:
        """A session factory whose every checkout waits, like a pool at its limit."""

        def __call__(self):
            return self

        async def __aenter__(self):
            await asyncio.sleep(3600)

        async def __aexit__(self, *_exc):
            return False

    started = time.perf_counter()
    checks = await run_platform_health_checks(
        _Exhausted(), task_scheduler=None, channel_router=None, retention_worker=None, outbound_webhook_worker=None,
        connector_health_worker=None, analytics_worker=None, prefetch_worker=None, worker_monitor_worker=None,
        worker_agenda_worker=None, worker_report_worker=None, worker_pool_worker=None, sla_monitor_worker=None,
        secret_expiry_worker=None, session_workspace_cleanup_worker=None)
    assert time.perf_counter() - started < 1.0  # well inside the probe's 5 s
    assert checks["database"]["status"] == "ok"
    assert evaluate_platform_health_summary(checks)["status"] != "error"
    await asyncio.sleep(0.3)  # the background store gives up on the busy pool, quietly
    assert not health_checks._persisting
    await probe.dispose()


def test_the_probe_engine_has_no_pool_and_sqlite_keeps_the_session() -> None:
    from sqlalchemy.pool import NullPool

    from app.services.observability import health_checks

    sqlite = create_async_engine("sqlite+aiosqlite:///:memory:")
    assert health_checks._engine_for_probe(async_sessionmaker(sqlite)) is None
    postgres = create_async_engine("postgresql+asyncpg://u:p@db.invalid/oe")
    probe = health_checks._engine_for_probe(async_sessionmaker(postgres))
    assert probe is not None and isinstance(probe.pool, NullPool) and probe.url == postgres.url


@pytest.mark.asyncio
async def test_concurrent_stores_of_new_components_never_collide(tmp_path, caplog) -> None:
    """Two stores at once (api and worker, or two probes) never both read "no row" and insert (UNIQUE
    platform_health_checks.component): one upsert per store keeps one row per component with the newest result."""
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models import PlatformHealthCheck
    from app.services.observability import health_checks

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'health.db'}", connect_args={"timeout": 30})
    async with engine.begin() as connection:
        await connection.run_sync(PlatformHealthCheck.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    def checks(status: str) -> dict:
        return {name: {"status": status, "response_time_ms": 3, "error": None} for name in ("database", "scheduler")}

    with caplog.at_level("ERROR", logger=health_checks.logger.name):
        await asyncio.gather(*(health_checks._persist_platform_health_checks(factory, checks("ok")) for _ in range(5)))
    await health_checks._persist_platform_health_checks(factory, checks("degraded"))

    async with factory() as db:
        rows = (await db.execute(select(PlatformHealthCheck.component, PlatformHealthCheck.status))).all()
    assert sorted(rows) == [("database", "degraded"), ("scheduler", "degraded")]
    assert "Failed to persist platform health checks" not in caplog.text
    await engine.dispose()



@pytest.mark.asyncio
async def test_a_scrape_shows_the_newest_health_run_and_never_runs_one(client, db, monkeypatch) -> None:
    """Metrics never go through the database. /metrics shows the health of this process's newest run
    (the health endpoint, the probes, the API's health loop) with its time, and runs no check itself."""
    import time

    from app.services.observability import health_checks
    from tests.observability_support import admin_user, call_as

    health_checks.forget_platform_health_checks()
    admin = await admin_user(db)

    async def never(*_args, **_kwargs):
        raise AssertionError("a scrape must not run the health checks")

    text = (await call_as(client, "GET", "/metrics", admin)).text
    assert "# TYPE octryx_platform_health_checked_timestamp_seconds gauge" in text
    assert "octryx_platform_health_status{" not in text  # no run yet: nothing to show

    assert (await client.get("/api/v1/health")).status_code in (200, 503)
    monkeypatch.setattr(health_checks, "run_platform_health_checks", never)
    text = (await call_as(client, "GET", "/metrics", admin)).text
    checked = float(next(line for line in text.splitlines()
                         if line.startswith("octryx_platform_health_checked_timestamp_seconds ")).split()[1])
    assert abs(checked - time.time()) < 60
    assert 'octryx_platform_component_health{component="database",status="ok"} 1' in text
    assert sum(line.endswith(" 1") for line in text.splitlines()
               if line.startswith("octryx_platform_health_status{")) == 1
