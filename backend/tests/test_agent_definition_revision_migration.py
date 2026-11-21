"""The ``agent_definition_revisions`` table as ``alembic upgrade head`` builds it on a scratch SQLite database.

- the table has the documented columns, indexes, unique constraint and foreign keys;
- the retained ``agent_definitions`` / ``agent_steps`` tables are untouched;
- the unique ``(definition_id, revision_number)`` constraint is enforced.

Alembic's ``env.py`` calls ``asyncio.run`` internally, so ``command.upgrade`` runs in a worker thread rather than
inside pytest-asyncio's live loop.
"""

from __future__ import annotations

import concurrent.futures
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

TABLE_NAME = "agent_definition_revisions"


EXPECTED_COLUMNS = {
    "id",
    "definition_id",
    "revision_number",
    "status",
    "checksum",
    "snapshot_json",
    "validation_json",
    "restored_from_revision_id",
    "created_by",
    "created_at",
    "published_by",
    "published_at",
    "approved_by",
    "approved_at",
}


def _alembic_config(db_path: Path) -> Config:
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option(
        "script_location", str((alembic_ini.parent / "alembic").resolve())
    )
    # alembic/env.py hard-codes an async driver; use aiosqlite for the scratch DB.
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    config.attributes["database_url"] = f"sqlite+aiosqlite:///{db_path}"  # wins over an inherited DATABASE_URL
    return config


def _run_alembic(config: Config, action: str, *revisions: str) -> None:
    runner = command.upgrade if action == "upgrade" else command.downgrade

    def _do() -> None:
        for revision in revisions:
            runner(config, revision)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(_do).result()


@pytest.fixture
def migrated_db(tmp_path):
    db_path = tmp_path / "agent_definition_revisions.db"
    config = _alembic_config(db_path)
    _run_alembic(config, "upgrade", "head")
    engine = sa.create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    try:
        yield config, engine
    finally:
        engine.dispose()


def test_upgrade_head_creates_the_revision_table(migrated_db):
    _, engine = migrated_db
    inspector = sa.inspect(engine)

    assert TABLE_NAME in inspector.get_table_names()
    columns = {column["name"]: column for column in inspector.get_columns(TABLE_NAME)}
    assert set(columns) == EXPECTED_COLUMNS
    for required in ("definition_id", "revision_number", "checksum", "snapshot_json", "created_by"):
        assert columns[required]["nullable"] is False, required
    for optional in ("validation_json", "restored_from_revision_id", "published_by", "published_at", "approved_by",
                     "approved_at"):
        assert columns[optional]["nullable"] is True, optional

    index_names = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
    assert {
        f"ix_{TABLE_NAME}_definition_id",
        f"ix_{TABLE_NAME}_checksum",
        f"ix_{TABLE_NAME}_restored_from_revision_id",
        f"ix_{TABLE_NAME}_definition_status",
    } <= index_names

    unique_constraints = {
        constraint["name"]: constraint["column_names"]
        for constraint in inspector.get_unique_constraints(TABLE_NAME)
    }
    assert unique_constraints["uq_agent_definition_revision_number"] == [
        "definition_id",
        "revision_number",
    ]

    foreign_keys = {
        tuple(fk["constrained_columns"]): (fk["referred_table"], fk.get("options", {}))
        for fk in inspector.get_foreign_keys(TABLE_NAME)
    }
    assert foreign_keys[("definition_id",)][0] == "agent_definitions"
    assert foreign_keys[("definition_id",)][1].get("ondelete") == "CASCADE"
    assert foreign_keys[("restored_from_revision_id",)][0] == TABLE_NAME
    assert foreign_keys[("restored_from_revision_id",)][1].get("ondelete") == "SET NULL"


def test_retained_agent_aggregate_tables_are_unchanged(migrated_db):
    _, engine = migrated_db
    inspector = sa.inspect(engine)

    definition_columns = {
        column["name"] for column in inspector.get_columns("agent_definitions")
    }
    assert "revision_number" not in definition_columns
    assert "published_revision_id" not in definition_columns
    assert {"id", "owner_id", "project_id", "name", "agent_type", "is_active"} <= (
        definition_columns
    )
    step_columns = {column["name"] for column in inspector.get_columns("agent_steps")}
    assert {"id", "agent_id", "position", "allowed_tools_json"} <= step_columns


def test_revision_number_is_unique_per_definition(migrated_db):
    _, engine = migrated_db
    definition_id = str(uuid.uuid4())
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO agent_definitions (id, owner_id, name) "
                "VALUES (:id, :owner, 'Migration fixture')"
            ),
            {"id": definition_id, "owner": str(uuid.uuid4())},
        )
        for revision_number in (1, 2):
            _insert_revision(connection, definition_id, revision_number)

    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            _insert_revision(connection, definition_id, 2)


def _insert_revision(connection, definition_id: str, revision_number: int) -> None:
    connection.execute(
        sa.text(
            f"INSERT INTO {TABLE_NAME} "
            "(id, definition_id, revision_number, status, checksum, snapshot_json, "
            " created_by, created_at) "
            "VALUES (:id, :definition_id, :revision_number, 'draft', :checksum, '{}', "
            " :created_by, CURRENT_TIMESTAMP)"
        ),
        {
            "id": str(uuid.uuid4()),
            "definition_id": definition_id,
            "revision_number": revision_number,
            "checksum": f"{revision_number:064d}",
            "created_by": str(uuid.uuid4()),
        },
    )


def _stamped_revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
