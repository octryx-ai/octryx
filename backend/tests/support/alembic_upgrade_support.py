"""Upgrade tests: a database built at an older revision, seeded with synthetic rows, then upgraded to head,
on the parity tests' scratch databases (SQLite, and PostgreSQL when ``OCTRYX_TEST_POSTGRES_URL`` is set)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from tests.alembic_model_parity_support import ScratchDatabase, migrated_database

# The schema of an installed 0.0.1.
BASELINE_REVISION = "a0001baseline"


@contextmanager
def upgraded_database(
    dialect: str,
    directory: Path,
    seed: Callable[[Connection], Any],
    *,
    revision: str = BASELINE_REVISION,
) -> Iterator[ScratchDatabase]:
    with migrated_database(dialect, directory, revision=revision) as database:
        database.run(seed)
        with pytest.MonkeyPatch.context() as monkeypatch:
            database.migrate(monkeypatch)
        yield database


def insert_row(connection: Connection, table: str, **values: Any) -> None:
    # Reflected, because the table's model may no longer exist at head.
    connection.execute(sa.Table(table, sa.MetaData(), autoload_with=connection).insert().values(**values))


def table_names(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())
