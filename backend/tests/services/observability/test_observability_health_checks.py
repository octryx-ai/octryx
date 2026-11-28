from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.observability.health_checks import evaluate_platform_health_summary


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
