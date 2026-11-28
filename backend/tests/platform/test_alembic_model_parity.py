"""A fresh ``alembic upgrade head`` must build the schema that the models declare."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Connection

from app.db import core as db_core
from tests.alembic_model_parity_support import (
    BACKEND_DIR,
    DIALECTS,
    MIGRATION_METADATA,
    ScratchDatabase,
    assert_exact_residual,
    head_revision,
    migrated_database,
    missing_model_objects,
    schema_drift,
    schema_snapshot,
    scratch_database,
)
from tests.fresh_interpreter_support import run_python_probe
from tests.platform.alembic_model_parity_schema_support import WEBHOOK_SECRET_CONTRACT, _schema_state
from tests.support.alembic_model_parity_residual import (
    NEVER_MODELLED_INDEX,
    NEVER_MODELLED_TABLE,
    RESIDUAL_BASELINE,
    RESIDUAL_DRIFT_BOTH_DIALECTS,
    SQLITE_DIALECT_DIFFERENCE,
    expected_residual,
)


@pytest.fixture(scope="module", params=DIALECTS)
def migrated_template(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[ScratchDatabase]:
    with migrated_database(request.param, tmp_path_factory.mktemp("alembic-parity")) as database:
        yield database


@pytest.fixture
def fresh_database(migrated_template: ScratchDatabase, tmp_path: Path) -> Iterator[ScratchDatabase]:
    with scratch_database(migrated_template.dialect, tmp_path, template=migrated_template) as database:
        yield database


def _index_names(snapshot: dict[str, Any]) -> set[tuple[str, str]]:
    return {(table, index[0]) for table, shape in snapshot.items() for index in shape.get("indexes", [])}


def _rendered_index_names(connection: Connection, names: set[tuple[str, str]]) -> set[tuple[str, str]]:
    preparer = connection.dialect.identifier_preparer
    indexes = {
        (index.table.name, index.name): index for table in MIGRATION_METADATA.sorted_tables for index in table.indexes
    }
    return {(table, preparer.format_index(indexes[(table, name)]).strip('"')) for table, name in names}


ENTRY_POINT_PROBE = """
import importlib, json, sys
from app.db import Base
from app.db.migration_metadata import load_migration_metadata
registry = set(load_migration_metadata().tables)
importlib.import_module(sys.argv[1])
print("UNREGISTERED-TABLES " + json.dumps(sorted(set(Base.metadata.tables) - registry)))
"""


def test_fresh_upgrade_builds_every_model_table_and_column(fresh_database: ScratchDatabase) -> None:
    state = fresh_database.run(_schema_state)

    assert state["version"] == head_revision()
    assert missing_model_objects(state["drift"]) == []
    assert set(MIGRATION_METADATA.tables) <= state["tables"]
    assert state["webhook_secret_contract"] == WEBHOOK_SECRET_CONTRACT


def test_fresh_upgrade_leaves_exactly_the_classified_residual(fresh_database: ScratchDatabase) -> None:
    assert_exact_residual(fresh_database.run(schema_drift), expected_residual(fresh_database.dialect))


def test_residual_is_classified_and_can_only_shrink() -> None:
    # Only a SQLite-only entry may be an accepted dialect difference.
    assert SQLITE_DIALECT_DIFFERENCE not in {**expected_residual("postgresql"), **RESIDUAL_DRIFT_BOTH_DIALECTS}.values()
    for dialect, baseline in RESIDUAL_BASELINE.items():
        residual = expected_residual(dialect)
        assert len(residual) <= baseline, f"the {dialect} residual grew beyond its baseline"
        assert missing_model_objects(set(residual)) == [], "a missing table or column is never an accepted residual"
        accepted = {NEVER_MODELLED_TABLE, NEVER_MODELLED_INDEX} | (
            {SQLITE_DIALECT_DIFFERENCE} if dialect == "sqlite" else set())
        assert all(label in accepted for label in residual.values())


@pytest.mark.parametrize("entry_point", ["app.main", "app.worker_main", "app.code_indexer_main"])
def test_runtime_entry_points_register_no_table_outside_the_migration_metadata(entry_point: str) -> None:
    result = run_python_probe(ENTRY_POINT_PROBE, entry_point, cwd=BACKEND_DIR)
    assert result.returncode == 0, result.stderr[-3000:]
    report = [line for line in result.stdout.splitlines() if line.startswith("UNREGISTERED-TABLES ")]
    assert report, result.stdout[-3000:]
    assert json.loads(report[-1].removeprefix("UNREGISTERED-TABLES ")) == []


def test_create_all_after_the_upgrade_creates_nothing(
    fresh_database: ScratchDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = fresh_database.run(schema_snapshot)

    fresh_database.run(MIGRATION_METADATA.create_all)

    assert fresh_database.run(schema_snapshot) == before

    # The startup index backfill still adds exactly the model-named duplicates of drift class G (a pair
    # that shares one name differs only in its unique flag, so the backfill skips that name).
    monkeypatch.setattr(db_core, "_is_sqlite", fresh_database.dialect == "sqlite")
    fresh_database.run(db_core._create_missing_indexes)
    added = _index_names(fresh_database.run(schema_snapshot)) - _index_names(before)
    residual = expected_residual(fresh_database.dialect)
    renamed = {
        (key[1], key[2])
        for key in residual
        if key[0] == "add_index" and ("remove_index", key[1], key[2]) not in residual
    }
    assert added == fresh_database.run(lambda connection: _rendered_index_names(connection, renamed))
