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
from tests.support.alembic_upgrade_support import insert_row, table_names, upgraded_database

PREVIOUS_REVISION = "a0002unwired"
NOW = dt.datetime(2026, 11, 1, 12, 0)
WORKSPACE, WORKER = "workspace-0001", "worker-0001"


def _seed(connection: Connection) -> None:
    insert_row(connection, "projects", id=WORKSPACE, name="demo-shop", source_type="local", is_system=False,
               access_mode="private")
    insert_row(connection, "agent_workers", id=WORKER, project_id=WORKSPACE, name="demo-worker", role="Ops",
               schedule_type="always_on", timezone="UTC", autonomy_level="supervised", trust_score=0.5,
               total_tasks_completed=0, total_incidents_resolved=0, is_active=True)
    for index in (1, 2):
        insert_row(connection, "distributed_workers", id=f"registration-000{index}", worker_id=WORKER,
                   project_id=WORKSPACE, backend="database", status="ready", domains=["kubernetes"],
                   capabilities={"connectors_verified": True}, is_active=1, registered_at=NOW, last_heartbeat=NOW)


def _rows(connection: Connection, table: str) -> list[tuple[str, str]]:
    return list(connection.execute(sa.text(f"SELECT id, name FROM {table} WHERE id = :id"),
                                   {"id": WORKSPACE if table == "projects" else WORKER}).tuples())


@pytest.fixture(scope="module", params=DIALECTS)
def upgraded(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[ScratchDatabase]:
    with upgraded_database(request.param, tmp_path_factory.mktemp("upgrade-a0002"), _seed,
                           revision=PREVIOUS_REVISION) as database:
        yield database


def test_the_upgrade_reaches_head(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(alembic_version) == head_revision()


def test_the_upgrade_drops_the_distributed_workers_with_their_rows(upgraded: ScratchDatabase) -> None:
    assert "distributed_workers" not in upgraded.run(table_names)


def test_the_upgrade_keeps_the_workspace_and_its_worker(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(lambda connection: _rows(connection, "projects")) == [(WORKSPACE, "demo-shop")]
    assert upgraded.run(lambda connection: _rows(connection, "agent_workers")) == [(WORKER, "demo-worker")]


def test_the_upgraded_schema_matches_the_models(upgraded: ScratchDatabase) -> None:
    assert_exact_residual(upgraded.run(schema_drift), expected_residual(upgraded.dialect))


def test_the_downgrade_restores_the_empty_table(upgraded: ScratchDatabase, tmp_path: Path) -> None:
    with scratch_database(upgraded.dialect, tmp_path, template=upgraded) as database:
        with pytest.MonkeyPatch.context() as monkeypatch:
            database.migrate(monkeypatch, revision=PREVIOUS_REVISION, down=True)
        assert "distributed_workers" in database.run(table_names)
        assert database.run(lambda connection: connection.execute(
            sa.text("SELECT COUNT(*) FROM distributed_workers")).scalar_one()) == 0
