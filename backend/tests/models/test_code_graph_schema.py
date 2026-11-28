from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    CodeGraphChunk,
    CodeGraphEdge,
    CodeGraphFile,
    CodeGraphNode,
    CodeGraphReference,
    CodeGraphRepository,
    CodeGraphRoute,
    CodeGraphRun,
    CodeGraphSnapshot,
    CodeGraphStaleness,
    CodeGraphSymbol,
)
from tests.models.code_graph_schema_support import _seed_full_code_graph_schema


async def _schema_table_names(db) -> set[str]:
    connection = await db.connection()
    return await connection.run_sync(lambda sync_connection: set(inspect(sync_connection).get_table_names()))


async def _schema_columns(db, table_name: str) -> set[str]:
    connection = await db.connection()
    return await connection.run_sync(
        lambda sync_connection: {column["name"] for column in inspect(sync_connection).get_columns(table_name)}
    )


@pytest.mark.asyncio
async def test_code_graph_schema_tables_and_secret_column_guardrail(db):
    table_names = await _schema_table_names(db)

    assert {
        "code_graph_repositories",
        "code_graph_runs",
        "code_graph_files",
        "code_graph_nodes",
        "code_graph_symbols",
        "code_graph_edges",
        "code_graph_references",
        "code_graph_routes",
        "code_graph_chunks",
        "code_graph_snapshots",
        "code_graph_staleness",
        "code_graph_unresolved_references",
    } <= table_names

    forbidden_fragments = {"password", "secret", "credential", "private_key", "api_key"}
    for table_name in table_names:
        if not table_name.startswith("code_graph_"):
            continue
        for column_name in await _schema_columns(db, table_name):
            assert not any(fragment in column_name.lower() for fragment in forbidden_fragments), (
                table_name,
                column_name,
            )


@pytest.mark.asyncio
async def test_code_graph_schema_uniqueness_and_cascade_delete(db):
    seeded = await _seed_full_code_graph_schema(db)

    duplicate_symbol = CodeGraphSymbol(
        id=str(uuid.uuid4()),
        run_id=seeded["run_id"],
        graph_repository_id=seeded["graph_repository_id"],
        stable_symbol_id=seeded["source_symbol_stable_id"],
        kind="function",
        name="handler",
    )
    db.add(duplicate_symbol)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()

    graph_repository = await db.get(CodeGraphRepository, seeded["graph_repository_id"])
    await db.delete(graph_repository)
    await db.commit()

    for model in [
        CodeGraphRun,
        CodeGraphFile,
        CodeGraphNode,
        CodeGraphSymbol,
        CodeGraphEdge,
        CodeGraphReference,
        CodeGraphRoute,
        CodeGraphChunk,
        CodeGraphSnapshot,
        CodeGraphStaleness,
    ]:
        count = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        assert count == 0, model.__name__
