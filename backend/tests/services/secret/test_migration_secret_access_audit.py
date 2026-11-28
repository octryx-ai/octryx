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
from tests.support.alembic_upgrade_support import BASELINE_REVISION, insert_row, upgraded_database

NOW = dt.datetime(2026, 11, 1, 12, 0)
WORKSPACE, SECRET, GLOBAL_SECRET = "workspace-0001", "secret-0001", "secret-0002"


def _seed_0_0_1(connection: Connection) -> None:
    insert_row(connection, "projects", id=WORKSPACE, name="demo-shop", source_type="local", is_system=False,
               access_mode="private")
    insert_row(connection, "stored_secrets", id=SECRET, name="demo-token", secret_type="api_key",
               project_id=WORKSPACE)
    insert_row(connection, "stored_secrets", id=GLOBAL_SECRET, name="demo-global", secret_type="api_key")
    for row_id, secret_id in (("audit-0001", SECRET), ("audit-0002", GLOBAL_SECRET), ("audit-0003", None)):
        insert_row(connection, "secret_access_audit_log", id=row_id, secret_id=secret_id, action="read",
                   outcome="success", created_at=NOW)


def _audit_rows(connection: Connection) -> list[tuple]:
    return list(connection.execute(sa.text(
        "SELECT id, secret_id, project_id, principal, purpose FROM secret_access_audit_log ORDER BY id")).tuples())


@pytest.fixture(scope="module", params=DIALECTS)
def upgraded(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[ScratchDatabase]:
    with upgraded_database(request.param, tmp_path_factory.mktemp("upgrade-secret-audit"), _seed_0_0_1) as database:
        yield database


def test_the_upgrade_from_0_0_1_reaches_head(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(alembic_version) == head_revision()


def test_the_upgrade_gives_each_existing_read_its_secrets_workspace(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(_audit_rows) == [
        ("audit-0001", SECRET, WORKSPACE, None, None),
        ("audit-0002", GLOBAL_SECRET, None, None, None),
        ("audit-0003", None, None, None, None),
    ]


def test_the_upgraded_schema_matches_the_models(upgraded: ScratchDatabase) -> None:
    assert_exact_residual(upgraded.run(schema_drift), expected_residual(upgraded.dialect))


def test_the_downgrade_drops_the_new_columns_and_keeps_the_rows(upgraded: ScratchDatabase, tmp_path: Path) -> None:
    with scratch_database(upgraded.dialect, tmp_path, template=upgraded) as database:
        with pytest.MonkeyPatch.context() as monkeypatch:
            database.migrate(monkeypatch, revision=BASELINE_REVISION, down=True)
        columns = database.run(lambda connection: {column["name"] for column in
                                                   sa.inspect(connection).get_columns("secret_access_audit_log")})
        assert {"project_id", "principal", "purpose"} & columns == set()
        assert database.run(lambda connection: connection.execute(
            sa.text("SELECT COUNT(*) FROM secret_access_audit_log")).scalar_one()) == 3
