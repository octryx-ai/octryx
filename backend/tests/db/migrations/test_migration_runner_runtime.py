from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from tests.alembic_model_parity_support import (
    DIALECTS,
    ScratchDatabase,
    alembic_version,
    assert_exact_residual,
    head_revision,
    schema_drift,
    scratch_database,
)
from tests.support.alembic_model_parity_residual import expected_residual
from tests.support.alembic_upgrade_support import insert_row, upgraded_database

PREVIOUS_REVISION = "a0005channel_secrets"
USER, DEVICE = "user-0001", "dev_upgrade0001"
NOW = dt.datetime(2026, 11, 1, 12, 0)


def _seed(connection: Connection) -> None:
    insert_row(connection, "users", id=USER, username="upgrade-user", email="upgrade@example.invalid",
               password_hash="synthetic", auth_source="local", account_type="human")
    insert_row(connection, "user_devices", id=DEVICE, owner_user_id=USER, name="Laptop", name_key="laptop",
               os="macos", public_key="synthetic-key", folders=["/work"], profiles=["governed"],
               max_parallel_jobs=1, status="active", paused=False, created_at=NOW)


def _device(connection: Connection) -> list[tuple]:
    return list(connection.execute(sa.text("SELECT id, name, runtime FROM user_devices WHERE id = :id"),
                                   {"id": DEVICE}).tuples())


@pytest.fixture(scope="module", params=DIALECTS)
def upgraded(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[ScratchDatabase]:
    with upgraded_database(request.param, tmp_path_factory.mktemp("upgrade-a0005"), _seed,
                           revision=PREVIOUS_REVISION) as database:
        yield database


def test_the_upgrade_reaches_head(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(alembic_version) == head_revision()


def test_an_existing_device_keeps_its_row_and_reports_no_runtime(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(_device) == [(DEVICE, "Laptop", None)]


def test_the_upgraded_schema_matches_the_models(upgraded: ScratchDatabase) -> None:
    assert_exact_residual(upgraded.run(schema_drift), expected_residual(upgraded.dialect))


def test_the_downgrade_drops_the_column_and_keeps_the_device(upgraded: ScratchDatabase, tmp_path: Path) -> None:
    with scratch_database(upgraded.dialect, tmp_path, template=upgraded) as database:
        with pytest.MonkeyPatch.context() as monkeypatch:
            database.migrate(monkeypatch, revision=PREVIOUS_REVISION, down=True)
        columns = database.run(lambda connection: {column["name"] for column in
                                                   sa.inspect(connection).get_columns("user_devices")})
        assert "runtime" not in columns
        assert database.run(lambda connection: connection.execute(
            sa.text("SELECT name FROM user_devices WHERE id = :id"), {"id": DEVICE}).scalar_one()) == "Laptop"
