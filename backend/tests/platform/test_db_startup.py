from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.sqlite import run_sqlite_startup_maintenance, sqlite_backup_candidates, sqlite_sidecar_paths
from app.db.startup import ensure_runtime_database_ready
from app.models import Project


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_ensure_runtime_database_ready_initializes_schema_then_runs_seed(monkeypatch):
    calls: list[tuple[str, object]] = []

    async def fake_init_db():
        calls.append(("init_db", None))

    async def fake_run_sqlite_startup_maintenance(engine, *, database_url):
        calls.append(("maintenance", database_url))

    class FakeSessionFactory:
        def __call__(self):
            return _FakeSessionContext("db-session")

    async def fake_seed_database(db):
        calls.append(("seed_database", db))

    monkeypatch.setattr("app.db.startup.init_db", fake_init_db)
    monkeypatch.setattr(
        "app.db.startup.run_sqlite_startup_maintenance",
        fake_run_sqlite_startup_maintenance,
    )
    monkeypatch.setattr("app.db.startup.settings.database_url", "sqlite+aiosqlite:////tmp/test.db")

    await ensure_runtime_database_ready(FakeSessionFactory(), seed_database=fake_seed_database)

    assert calls == [
        ("init_db", None),
        ("seed_database", "db-session"),
        ("maintenance", "sqlite+aiosqlite:////tmp/test.db"),
    ]


@pytest.mark.asyncio
async def test_ensure_runtime_database_ready_skips_seed_when_not_requested(monkeypatch):
    calls: list[str] = []

    async def fake_init_db():
        calls.append("init_db")

    async def fake_run_sqlite_startup_maintenance(engine, *, database_url):
        calls.append(f"maintenance:{database_url}")

    class ExplodingSessionFactory:
        def __call__(self):
            raise AssertionError("session factory should not be used without a seeder")

    monkeypatch.setattr("app.db.startup.init_db", fake_init_db)
    monkeypatch.setattr(
        "app.db.startup.run_sqlite_startup_maintenance",
        fake_run_sqlite_startup_maintenance,
    )
    monkeypatch.setattr("app.db.startup.settings.database_url", "sqlite+aiosqlite:////tmp/test.db")

    await ensure_runtime_database_ready(ExplodingSessionFactory())

    assert calls == ["init_db", "maintenance:sqlite+aiosqlite:////tmp/test.db"]


def test_sqlite_helpers_report_sidecars_and_backup_candidates(tmp_path: Path):
    db_path = tmp_path / "octryx.db"
    db_path.write_text("db")
    (tmp_path / "octryx.db.pre_cleanup_20260331_204340.bak").write_text("bak1")
    (tmp_path / "octryx.db.snapshot.bak").write_text("bak2")

    sidecars = sqlite_sidecar_paths(db_path)

    assert sidecars["wal"] == tmp_path / "octryx.db-wal"
    assert sidecars["shm"] == tmp_path / "octryx.db-shm"
    assert sidecars["init_lock"] == tmp_path / "octryx.db.init.lock"
    assert sqlite_backup_candidates(db_path) == [
        tmp_path / "octryx.db.pre_cleanup_20260331_204340.bak",
        tmp_path / "octryx.db.snapshot.bak",
    ]


@pytest.mark.asyncio
async def test_run_sqlite_startup_maintenance_uses_passive_checkpoint():
    statements: list[str] = []

    class FakeResult:
        def first(self):
            return (0, 12, 12)

    class FakeConnection:
        async def execute(self, statement):
            statements.append(str(statement))
            return FakeResult()

    class FakeBeginContext:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBeginContext()

    await run_sqlite_startup_maintenance(
        FakeEngine(),
        database_url="sqlite+aiosqlite:////tmp/test.db",
    )

    assert statements == [
        "PRAGMA journal_size_limit=67108864",
        "PRAGMA wal_checkpoint(PASSIVE)",
    ]


@pytest.mark.asyncio
async def test_async_session_normalizes_aware_datetimes_for_naive_columns(db):
    aware_now = datetime(2026, 4, 28, 20, 0, tzinfo=UTC)
    row = Project(
        name="postgres-normalization-check",
        description="Verifies naive UTC coercion before flush.",
        created_at=aware_now,
        updated_at=aware_now,
    )

    db.add(row)
    await db.commit()

    stored = (await db.execute(select(Project).where(Project.id == row.id))).scalar_one()
    expected = aware_now.replace(tzinfo=None)

    assert stored.created_at == expected
    assert stored.updated_at == expected
    assert stored.created_at.tzinfo is None
    assert stored.updated_at.tzinfo is None
