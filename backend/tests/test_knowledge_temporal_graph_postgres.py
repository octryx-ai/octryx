"""The Workspace temporal graph on PostgreSQL (graph on Postgres, part B), on a migrated pgvector server.

Entities and facts seeded into ``kg_node``/``kg_edge`` answer the product's fixed one-hop reads with the
record shape the read paths expect:

- every read is scoped by the driver's Workspace, never by a caller value;
- the episode, group, kind, entity, focus and substring selectors mean what the Cypher meant;
- the ranked edge search fuses a full-text and a cosine ranking inside one group;
- an unknown statement, or a known one with other parameters, is refused.

Skipped unless ``OCTRYX_TEST_POSTGRES_URL`` names a disposable server with pgvector.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.knowledge.temporal.changes import _FACTS, _FACTS_OF_KINDS
from app.services.knowledge.temporal.errors import GraphStoreError, GraphStoreState
from app.services.knowledge.temporal.fact_expansion import _DIRECT, _HOP
from app.services.knowledge.temporal.postgres_graph import PostgresGraphDriver
from app.services.knowledge.temporal.visualization_queries import FACTS_QUERY
from tests.alembic_model_parity_support import migrated_database, requires_postgres

pytestmark = requires_postgres


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[object]:
    with migrated_database("postgresql", Path(tmp_path_factory.mktemp("temporal-graph"))) as migrated:
        yield migrated


def _seed_project(connection: Connection) -> str:
    project_id = str(uuid.uuid4())
    connection.execute(
        text(
            "INSERT INTO projects (id, name, is_active, source_type, is_system, access_mode, created_at) "
            "VALUES (:id, :name, true, 'manual', false, 'team', :now)"
        ),
        {"id": project_id, "name": f"ws-{project_id[:8]}", "now": datetime(2026, 11, 5, 12, 0, 0)},
    )
    return project_id


def _axis(index: int) -> list[float]:
    vector = [0.0] * 384
    vector[index] = 1.0
    return vector


_NODES = ("Spring Boot 4", "Java 17", "Jackson 3", "Undertow")
_EDGES = (
    # key, source, target, relation, fact, episodes, embedding axis, group
    ("java", "Spring Boot 4", "Java 17", "REQUIRES", "Spring Boot 4 requires Java 17 or later", ["ep1"], 0, "boot"),
    ("jackson", "Spring Boot 4", "Jackson 3", "INTRODUCED", "Jackson 3 becomes the default", ["ep2"], 1, "boot"),
    ("undertow", "Spring Boot 4", "Undertow", "REMOVED", "Undertow support was removed", ["ep2"], 2, "boot"),
    ("other", "Java 17", "Jackson 3", "REQUIRES", "A fact of another product", ["ep1"], 3, "data"),
)


def _vector(values: list[float]) -> str:
    return "[" + ",".join(repr(value) for value in values) + "]"


async def _seed_graph(db, project_id: str) -> None:
    for name in _NODES:
        await db.execute(
            text(
                "INSERT INTO kg_node (project_id, uuid, name, group_id, labels, created_at) "
                "VALUES (:project_id, :uuid, :name, 'boot', CAST(:labels AS text[]), :created_at)"
            ),
            {"project_id": project_id, "uuid": f"n-{name}", "name": name, "labels": ["Entity"],
             "created_at": datetime(2026, 9, 29, 10, 0, 0)},
        )
    for key, source, target, relation, fact, episodes, axis, group in _EDGES:
        await db.execute(
            text(
                "INSERT INTO kg_edge (project_id, uuid, relation, fact, episodes, group_id, source_uuid, target_uuid, "
                "created_at, embedding) VALUES (:project_id, :uuid, :relation, :fact, CAST(:episodes AS text[]), "
                ":group_id, :source_uuid, :target_uuid, :created_at, CAST(CAST(:embedding AS text) AS vector))"
            ),
            {"project_id": project_id, "uuid": f"e-{key}", "relation": relation, "fact": fact, "episodes": episodes,
             "group_id": group, "source_uuid": f"n-{source}", "target_uuid": f"n-{target}",
             "created_at": datetime(2026, 9, 29, 10, 0, axis), "embedding": _vector(_axis(axis))},
        )
    await db.commit()


def _run(database, scenario):
    async def main():
        engine = create_async_engine(database.url)
        try:
            return await scenario(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(main())


def test_fixed_reads_answer_like_the_cypher(database):
    project_id = database.run(_seed_project)
    other = database.run(_seed_project)

    async def scenario(sessions):
        async with sessions() as db:
            await _seed_graph(db, project_id)
            await _seed_graph(db, other)
        driver = PostgresGraphDriver(project_id, sessions)
        facts, _, _ = await driver.execute_query(_FACTS, group="boot", episodes=["ep2"], limit=10)
        kinds, _, _ = await driver.execute_query(
            _FACTS_OF_KINDS, group="boot", episodes=["ep1", "ep2"], kinds=["REQUIRES"], limit=10
        )
        direct, _, _ = await driver.execute_query(_DIRECT, group="boot", episodes=["ep1"], limit=10)
        hop, _, _ = await driver.execute_query(_HOP, group="boot", entities=["n-Jackson 3"], limit=10)
        explorer, _, _ = await driver.execute_query(
            FACTS_QUERY, episodes=["ep1", "ep2"], query="undertow", focus="", limit=10
        )
        focus, _, _ = await driver.execute_query(
            FACTS_QUERY, episodes=["ep1", "ep2"], query="", focus="n-Java 17", limit=10
        )
        ranked = await driver.ranked_edges("which java is required", "boot", _axis(1), 10)
        return facts, kinds, direct, hop, explorer, focus, ranked

    facts, kinds, direct, hop, explorer, focus, ranked = _run(database, scenario)
    assert [row["uuid"] for row in facts] == ["e-jackson", "e-undertow"]
    assert facts[0]["source"] == "Spring Boot 4" and facts[0]["target"] == "Jackson 3"
    assert facts[0]["episodes"] == ["ep2"] and facts[0]["created_at"].startswith("2026-09-29 10:00:01")
    assert [row["uuid"] for row in kinds] == ["e-java"]
    assert [row["uuid"] for row in direct] == ["e-java"]
    assert [row["uuid"] for row in hop] == ["e-jackson"]
    assert [row["uuid"] for row in explorer] == ["e-undertow"]
    assert {row["uuid"] for row in focus} == {"e-java", "e-other"}
    lexical, semantic = ranked
    assert lexical == ["e-java"]
    assert semantic == ["e-jackson"]


def test_unknown_statements_and_parameters_are_refused(database):
    project_id = database.run(_seed_project)

    async def scenario(sessions):
        driver = PostgresGraphDriver(project_id, sessions)
        refused = []
        for statement, parameters in (
            ("MATCH (n) DETACH DELETE n", {}),
            (_FACTS, {"group": "boot", "episodes": [], "limit": 1, "extra": 1}),
        ):
            try:
                await driver.execute_query(statement, **parameters)
            except GraphStoreError as error:
                refused.append(error.state)
        return refused

    assert _run(database, scenario) == [GraphStoreState.CONTRACT_VIOLATION] * 2
