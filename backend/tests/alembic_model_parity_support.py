"""Shared helpers for the Alembic-versus-model parity tests (SQLite, and PostgreSQL when ``OCTRYX_TEST_POSTGRES_URL``
names a disposable server; only ``octryx_alembic_parity_*`` scratch databases are created and dropped)."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.db.migration_metadata import load_migration_metadata
from tests.support.alembic_model_parity_residual import DriftKey
from tests.support.postgres_env import postgres_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION_METADATA = load_migration_metadata()
POSTGRES_URL_ENV = "OCTRYX_TEST_POSTGRES_URL"
requires_postgres = pytest.mark.skipif(
    not postgres_url(),
    reason=f"set {POSTGRES_URL_ENV} to a disposable PostgreSQL server to run the PostgreSQL parity checks",
)
DIALECTS = ["sqlite", pytest.param("postgresql", marks=requires_postgres)]


def alembic_config(database_url: str) -> Config:
    # No ini file on purpose: alembic.ini's logging section would run ``fileConfig`` inside the
    # test process and disable every logger that other tests in this worker rely on.
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()


def migrate(database_url: str, monkeypatch: pytest.MonkeyPatch, *, revision: str = "head", down: bool = False) -> None:
    # ``alembic/env.py`` prefers the process DATABASE_URL over the configured URL, so pin it to the
    # database under test; an inherited DATABASE_URL must never be migrated by a test.
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = alembic_config(database_url)
    # Scratch SQLite migrations skip fsync (tests/support/scratch_sqlite_migrations.py, loaded by conftest.py).
    if down:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


def stamp(database_url: str, monkeypatch: pytest.MonkeyPatch, revision: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.stamp(alembic_config(database_url), revision)


def _drift_key(diff: tuple) -> DriftKey:
    kind = diff[0]
    if kind in ("add_table", "remove_table"):
        return (kind, diff[1].name)
    if kind in ("add_column", "remove_column"):
        return (kind, diff[2], diff[3].name)
    if kind in ("add_index", "remove_index"):
        return (kind, diff[1].table.name, diff[1].name)
    if kind in ("add_constraint", "remove_constraint"):
        constraint = diff[1]
        name = constraint.name or ",".join(column.name for column in constraint.columns)
        return (kind, constraint.table.name, name)
    if kind in ("add_fk", "remove_fk"):
        foreign_key = diff[1]
        columns = ",".join(column.name for column in foreign_key.columns)
        return (kind, foreign_key.table.name, f"{columns}->{foreign_key.referred_table.name}")
    if kind.startswith("modify_"):
        return (kind, diff[2], diff[3])
    # An operation this module does not classify yet: it always surfaces as new drift.
    return (kind, repr(diff))


def schema_drift(connection: Connection) -> set[DriftKey]:
    context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": False})
    keys: set[DriftKey] = set()
    for diff in compare_metadata(context, MIGRATION_METADATA):
        for item in diff if isinstance(diff, list) else [diff]:
            keys.add(_drift_key(item))
    return keys


def missing_model_objects(drift: set[DriftKey]) -> list[DriftKey]:
    return sorted(key for key in drift if key[0] in ("add_table", "add_column"))


def assert_exact_residual(drift: set[DriftKey], expected: dict[DriftKey, str]) -> None:
    unexpected = sorted(drift - expected.keys())
    resolved = sorted(expected.keys() - drift)
    assert not unexpected, f"New schema drift; add an Alembic migration or classify it in alembic_model_parity_residual: {unexpected}"
    assert not resolved, f"Listed drift no longer occurs; remove it from the residual: {resolved}"


def schema_snapshot(connection: Connection) -> dict[str, Any]:
    inspector = inspect(connection)
    snapshot: dict[str, Any] = {}
    for (_schema, table), columns in inspector.get_multi_columns().items():
        snapshot[table] = {"columns": sorted((c["name"], str(c["type"]), bool(c["nullable"])) for c in columns)}
    for (_schema, table), indexes in inspector.get_multi_indexes().items():
        snapshot[table]["indexes"] = sorted(
            (str(i["name"]), tuple(i["column_names"]), bool(i["unique"])) for i in indexes
        )
    for (_schema, table), uniques in inspector.get_multi_unique_constraints().items():
        snapshot[table]["uniques"] = sorted((str(u["name"]), tuple(u["column_names"])) for u in uniques)
    for (_schema, table), foreign_keys in inspector.get_multi_foreign_keys().items():
        snapshot[table]["foreign_keys"] = sorted(
            (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"])) for f in foreign_keys
        )
    for (_schema, table), checks in inspector.get_multi_check_constraints().items():
        snapshot[table]["checks"] = sorted(str(c.get("name")) for c in checks)
    return snapshot


def alembic_version(connection: Connection) -> str:
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


async def run_on(database_url: str, probe: Callable[[Connection], Any], **engine_options: Any) -> Any:
    engine = create_async_engine(database_url, **engine_options)
    try:
        async with engine.begin() as connection:
            return await connection.run_sync(probe)
    finally:
        await engine.dispose()


@dataclass(frozen=True)
class ScratchDatabase:
    dialect: str
    url: str

    def run(self, probe: Callable[[Connection], Any]) -> Any:
        return asyncio.run(run_on(self.url, probe))

    def migrate(self, monkeypatch: pytest.MonkeyPatch, *, revision: str = "head", down: bool = False) -> None:
        migrate(self.url, monkeypatch, revision=revision, down=down)

    def stamp(self, monkeypatch: pytest.MonkeyPatch, revision: str) -> None:
        stamp(self.url, monkeypatch, revision)


def _postgres_admin(statement: str) -> None:
    admin_url = make_url(postgres_url())
    assert admin_url.drivername == "postgresql+asyncpg", f"{POSTGRES_URL_ENV} must use postgresql+asyncpg"
    admin = admin_url.render_as_string(hide_password=False)
    asyncio.run(run_on(admin, lambda connection: connection.execute(text(statement)), isolation_level="AUTOCOMMIT"))


@contextmanager
def scratch_database(
    dialect: str, directory: Path, *, template: ScratchDatabase | None = None
) -> Iterator[ScratchDatabase]:
    if dialect == "sqlite":
        path = directory / f"{uuid.uuid4().hex}.db"
        if template is not None:
            shutil.copyfile(make_url(template.url).database, path)
        yield ScratchDatabase("sqlite", f"sqlite+aiosqlite:///{path}")
        return
    name = f"octryx_alembic_parity_{uuid.uuid4().hex[:12]}"
    source = f' TEMPLATE "{make_url(template.url).database}"' if template is not None else ""
    _postgres_admin(f'CREATE DATABASE "{name}"{source}')
    try:
        url = make_url(postgres_url()).set(database=name)
        yield ScratchDatabase("postgresql", url.render_as_string(hide_password=False))
    finally:
        _postgres_admin(f'DROP DATABASE IF EXISTS "{name}"')


@contextmanager
def migrated_database(dialect: str, directory: Path, *, revision: str = "head") -> Iterator[ScratchDatabase]:
    with scratch_database(dialect, directory) as database:
        with pytest.MonkeyPatch.context() as monkeypatch:
            database.migrate(monkeypatch, revision=revision)
        yield database
