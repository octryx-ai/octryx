"""Relationship extraction into the PostgreSQL graph, on a migrated pgvector server.

The governed model is replaced by a scripted answer; everything after it is the product path:
the profile's closed types and the self-check, entity resolution inside the product group,
fact deduplication across spans, one episode per span, a rerun that converges, and the fixed
graph read the changes page uses seeing the result.

Skipped unless ``OCTRYX_TEST_POSTGRES_URL`` names a disposable server with pgvector.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSource,
    KnowledgeSourceRevision,
)
from app.models.project.knowledge_temporal import KnowledgeGraphEpisode
from app.services.knowledge.embedding.catalog import embedding_space
from app.services.knowledge.embedding.port import EmbeddingRuntime
from app.services.knowledge.temporal.change_types import NOT_A_CHANGE_RELATION
from app.services.knowledge.temporal.changes import _FACTS
from app.services.knowledge.temporal.extraction_profiles import extraction_profiles
from app.services.knowledge.temporal.postgres_extraction import extract_batch
from app.services.knowledge.temporal.postgres_extraction_model import SpanInput, build_messages, episode_uuid
from app.services.knowledge.temporal.postgres_graph import PostgresGraphDriver
from tests.alembic_model_parity_support import migrated_database, requires_postgres
from tests.knowledge_evidence_text_support import ConceptEmbedder

pytestmark = requires_postgres

LOCAL = embedding_space("local_mlminilm_384_v1")
PROFILE = extraction_profiles()["change-records-v2"]
GROUP = "acme-orders-server"


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[object]:
    with migrated_database("postgresql", Path(tmp_path_factory.mktemp("graph-extraction"))) as migrated:
        yield migrated


class ScriptedModel:
    """Answers each call with the next scripted fact list, like the governed client would."""

    def __init__(self, *answers: list[dict]) -> None:
        self.answers = list(answers)
        self.prompts: list[list] = []

    async def _generate_response(self, messages, response_model=None, max_tokens=None):
        self.prompts.append(messages)
        answer = {"facts": self.answers.pop(0)}
        return response_model.model_validate(answer).model_dump() if response_model else answer


def _fact(passage, source, relation, target, fact, change=True):
    return {"passage": passage, "source": source, "relation": relation, "target": target, "fact": fact,
            "states_version_change": change}


async def _seed(sessions) -> tuple[str, str]:
    project_id, revision_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with sessions() as db:
        await db.execute(text(
            "INSERT INTO projects (id, name, is_active, source_type, is_system, access_mode, created_at) "
            "VALUES (:id, :name, true, 'manual', false, 'team', :now)"
        ), {"id": project_id, "name": f"ws-{project_id[:8]}", "now": datetime(2026, 11, 5)})
        source = KnowledgeEvidenceSource(project_id=project_id, source_key="manual", display_title="Server Manual")
        db.add(source)
        await db.flush()
        db.add(KnowledgeSourceRevision(
            id=revision_id, source_id=source.id, project_id=project_id, revision_ordinal=1, content_sha256="0" * 64,
            byte_size=1, media_type="application/pdf", object_bucket="b", object_key="k", parser_name="docling",
            parser_version="1", parser_sandbox="none", state=REVISION_STATE_PROJECTED,
        ))
        await db.commit()
    return project_id, revision_id


def _run(database, scenario):
    async def main():
        engine = create_async_engine(database.url)
        try:
            return await scenario(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _extract(sessions, project_id, revision_id, model, spans):
    embedding = EmbeddingRuntime(space=LOCAL, embedder=ConceptEmbedder(LOCAL))
    async with sessions() as db:
        result = await extract_batch(
            db, llm=model, embedding=embedding, profile=PROFILE, project_id=project_id, revision_id=revision_id,
            group=GROUP, version="3.2", title="Server Manual (version 3.2)", valid_at=datetime(2026, 10, 1),
            spans=spans,
        )
        await db.commit()
    return result


def test_the_prompt_carries_the_profile_and_numbered_passages():
    messages = build_messages(PROFILE, title="Manual", group=GROUP, version="3.2",
                              spans=[SpanInput(3, "first"), SpanInput(4, "second")])
    system, user = messages[0].content, messages[1].content
    assert "REQUIRES:" in system and "acme-orders-server" in system and "3.2" in system
    assert user == "Passage 1:\nfirst\n\nPassage 2:\nsecond"


def test_a_batch_writes_typed_facts_resolves_entities_and_records_every_span(database):
    async def scenario(sessions):
        project_id, revision_id = await _seed(sessions)
        spans = [SpanInput(1, "Requires PostgreSQL 14."), SpanInput(2, "Uses PostgreSQL."), SpanInput(3, "Contents")]
        first = ScriptedModel([
            _fact(1, "Acme Orders Server", "requires", "PostgreSQL 14", "Acme Orders Server 3.2 requires PostgreSQL 14."),
            _fact(2, "Acme Orders Server", "REQUIRES", "postgresql 14 ", "The server stores data in PostgreSQL.",
                  change=False),
            _fact(9, "Ghost", "REQUIRES", "Passage", "points at no passage"),
            _fact(1, "Loop", "USES", "loop", "an entity related to itself"),
        ])
        result = await _extract(sessions, project_id, revision_id, first, spans)
        # The same statement again from another span is one fact with two episodes.
        again = ScriptedModel([
            _fact(1, "Acme Orders Server", "REQUIRES", "PostgreSQL 14", "Acme Orders Server 3.2 requires PostgreSQL 14."),
        ])
        merged = await _extract(sessions, project_id, revision_id, again, [SpanInput(4, "Requires PostgreSQL 14 again.")])
        async with sessions() as db:
            nodes = (await db.execute(text("SELECT name FROM kg_node WHERE project_id = :p ORDER BY name"),
                                      {"p": project_id})).scalars().all()
            edges = (await db.execute(text(
                "SELECT relation, cardinality(episodes), embedding IS NOT NULL FROM kg_edge WHERE project_id = :p "
                "ORDER BY relation"), {"p": project_id})).all()
            episodes = (await db.execute(select(KnowledgeGraphEpisode.span_ordinal, KnowledgeGraphEpisode.edge_count)
                                         .where(KnowledgeGraphEpisode.revision_id == revision_id)
                                         .order_by(KnowledgeGraphEpisode.span_ordinal))).all()
        records, _, _ = await PostgresGraphDriver(project_id, sessions).execute_query(
            _FACTS, group=GROUP, episodes=[episode_uuid(project_id, revision_id, 1, PROFILE.profile_id)], limit=10
        )
        return result, merged, nodes, edges, episodes, records

    result, merged, nodes, edges, episodes, records = _run(database, scenario)
    assert (result.facts, result.dropped, result.demoted) == (2, 2, 1)
    # "PostgreSQL 14" and "postgresql 14 " are one entity.
    assert nodes == ["Acme Orders Server", "PostgreSQL 14"]
    assert edges == [(NOT_A_CHANGE_RELATION, 1, True), ("REQUIRES", 2, True)]
    assert merged.edges_merged == 1 and merged.edges_created == 0
    # Every span of a batch is recorded, also the one without a fact.
    assert [tuple(row) for row in episodes] == [(1, 1), (2, 1), (3, 0), (4, 1)]
    assert [(row["relation"], row["source"], row["target"]) for row in records] == [
        ("REQUIRES", "Acme Orders Server", "PostgreSQL 14")
    ]


def test_rerunning_a_span_replaces_its_episode_instead_of_adding_one(database):
    async def scenario(sessions):
        project_id, revision_id = await _seed(sessions)
        span = [SpanInput(1, "Requires Java 21.")]
        fact = [_fact(1, "Server", "REQUIRES", "Java 21", "The server requires Java 21.")]
        await _extract(sessions, project_id, revision_id, ScriptedModel(fact), span)
        await _extract(sessions, project_id, revision_id, ScriptedModel(fact), span)
        async with sessions() as db:
            episodes = (await db.execute(select(KnowledgeGraphEpisode.episode_uuid)
                                         .where(KnowledgeGraphEpisode.revision_id == revision_id))).scalars().all()
            edges = (await db.execute(text("SELECT episodes FROM kg_edge WHERE project_id = :p"),
                                      {"p": project_id})).scalars().all()
        return episodes, edges

    episodes, edges = _run(database, scenario)
    assert len(episodes) == 1
    assert edges == [episodes]
