"""The knowledge graph: bounded, governed and cited.

Contract tests only:

- an extraction run never outlives its claim;
- importing the Graphiti boundary never loads a dotenv file;
- the version-range and citation semantics of ``knowledge_changes``, with a fake graph.
"""

from __future__ import annotations

import dataclasses
import os

import pytest
from sqlalchemy import select

from app.models.project.knowledge_evidence import OUTBOX_OPERATION_EXTRACT_GRAPH, KnowledgeProjectionOutboxEntry
from app.models.project.knowledge_temporal import KnowledgeGraphEpisode
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.embedding.catalog import embedding_space
from app.services.knowledge.embedding.port import EmbeddingRuntime
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger.errors import EvidenceGraphNotConfiguredError
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.temporal import changes as changes_module
from app.services.knowledge.temporal.changes import STATE_NO_SOURCES, STATE_NOT_EXTRACTED, knowledge_changes
from app.services.knowledge.temporal.extraction_requests import request_graph_extraction
from tests.fresh_interpreter_support import run_python_probe
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.knowledge_evidence_text_support import ConceptEmbedder

LOCAL = embedding_space("local_mlminilm_384_v1")


def test_the_model_answer_is_the_first_complete_json_object():
    from app.services.knowledge.temporal.graphiti_llm import _json_object

    assert _json_object('Here you go:\n```json\n{"a": {"b": 1}}\n```\nAlso {"c": 2}') == {"a": {"b": 1}}
    assert _json_object('{broken {"ok": true}') == {"ok": True}
    with pytest.raises(ValueError):
        _json_object("no object at all")


def test_an_extraction_run_can_never_outlive_its_claim():
    from app.services.knowledge.projection.outbox_lease import MAX_LEASE_SECONDS
    from app.services.knowledge.projection.projector import GRAPH_RUN_TIMEOUT_SECONDS
    from app.services.knowledge.temporal.extraction_step import EPISODE_LEASE_SECONDS, EPISODE_TIMEOUT_SECONDS

    assert EPISODE_TIMEOUT_SECONDS < GRAPH_RUN_TIMEOUT_SECONDS < EPISODE_LEASE_SECONDS <= MAX_LEASE_SECONDS


_IMPORT_BOUNDARY_PROBE = """
import json, os, sys
import dotenv

calls = []
original = dotenv.load_dotenv


def recording_load_dotenv(*args, **kwargs):
    calls.append(os.environ.get("PYTHON_DOTENV_DISABLED"))
    return original(*args, **kwargs)


dotenv.load_dotenv = recording_load_dotenv
import app.services.knowledge.temporal.graphiti_boundary  # noqa: E402

json.dump({"calls": calls, "after": os.environ.get("PYTHON_DOTENV_DISABLED")}, sys.stdout)
"""


def test_importing_graphiti_never_loads_a_dotenv_file_into_the_process():
    # Graphiti's import-time load_dotenv() would copy the first .env above the installed package into
    # os.environ; alembic/env.py would then migrate that file's DATABASE_URL instead of the configured one.
    import json
    from pathlib import Path

    environment = {key: value for key, value in os.environ.items() if key != "PYTHON_DOTENV_DISABLED"}
    result = run_python_probe(_IMPORT_BOUNDARY_PROBE, cwd=Path(__file__).resolve().parents[1], env=environment)

    assert result.returncode == 0, "the Graphiti boundary probe failed; rerun this test with -s"
    observed = json.loads(result.stdout)
    assert observed["calls"] and set(observed["calls"]) == {"1"}
    assert observed["after"] is None


class FakeGraph:
    """Returns every stored fact whose episodes intersect the requested ones, like the fixed statement."""

    def __init__(self, facts: list[dict]) -> None:
        self.facts = facts

    async def execute_query(self, cypher, **parameters):
        wanted = set(parameters["episodes"])
        rows = [fact for fact in self.facts if set(fact["episodes"]) & wanted and fact["group"] == parameters["group"]]
        return rows, None, None

    async def close(self):
        pass


async def _library(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime(embedding=EmbeddingRuntime(space=LOCAL, embedder=ConceptEmbedder(LOCAL)))
    revisions = {}
    for version in ("3.5", "4.0", "4.1"):
        ingested = await ingest_text_source(
            db,
            runtime=runtime,
            authorized=authorized,
            source_key=f"sb-{version.replace('.', '-')}-release-notes",
            display_title=f"Spring Boot {version} Release Notes",
            declared_media_type="text/markdown",
            data=f"# Spring Boot {version}\n\nChanges of {version}.\n".encode(),
            created_by=user_id,
            source_url=f"https://example.com/sb-{version}",
            products="spring-boot",
            version=version,
        )
        revisions[version] = ingested.revision_id
    while await EvidenceProjector(runtime).project_once(db, worker_id="test") is not None:
        pass
    return authorized, runtime, revisions


async def test_changes_are_the_cited_facts_of_the_version_range_and_say_when_nothing_was_extracted(db, monkeypatch):
    authorized, runtime, revisions = await _library(db)

    assert (await knowledge_changes(db, runtime=runtime, authorized=authorized, product="spring-boot",
                                    from_version="3.5", to_version="4.0")).state == STATE_NOT_EXTRACTED
    assert (await knowledge_changes(db, runtime=runtime, authorized=authorized, product="data-platform",
                                    to_version="4.0")).state == STATE_NO_SOURCES

    for version, episode in (("3.5", "ep-35"), ("4.0", "ep-40"), ("4.1", "ep-41")):
        db.add(KnowledgeGraphEpisode(episode_uuid=episode, project_id=authorized.project_id,
                                     revision_id=revisions[version], span_ordinal=1, group_id="spring-boot",
                                     extraction_profile="change-records-v1"))
    await db.commit()
    graph = FakeGraph([
        {"uuid": "f35", "relation": "INTRODUCED", "fact": "3.5 adds X", "episodes": ["ep-35"], "source": "a", "target": "b",
         "group": "spring-boot"},
        {"uuid": "f40", "relation": "REQUIRES", "fact": "Spring Boot 4.0 requires Java 17", "episodes": ["ep-40"],
         "source": "Spring Boot 4.0", "target": "Java 17", "group": "spring-boot"},
        {"uuid": "f41", "relation": "INTRODUCED", "fact": "4.1 adds Y", "episodes": ["ep-41"], "source": "a", "target": "c",
         "group": "spring-boot"},
    ])
    monkeypatch.setattr(changes_module, "PostgresGraphDriver", lambda project_id: graph)

    result = await knowledge_changes(
        db, runtime=runtime, authorized=authorized, product="spring-boot", from_version="3.5", to_version="4.0"
    )

    assert result.state == "ok" and result.versions == ("4.0",)
    (fact,) = result.facts
    assert fact.fact == "Spring Boot 4.0 requires Java 17" and fact.version == "4.0"
    assert fact.citation.source_title == "Spring Boot 4.0 Release Notes"
    assert fact.citation.source_url == "https://example.com/sb-4.0"
    with pytest.raises(Exception):  # an empty range is a refused request, not "no changes"
        await knowledge_changes(db, runtime=runtime, authorized=authorized, product="spring-boot",
                                from_version="4.0", to_version="3.5")
    assert changes_module.MAX_FACTS == 200


async def test_extraction_is_owed_only_on_request_and_only_with_an_embedding_space(db):
    authorized, runtime, revisions = await _library(db)
    with pytest.raises(EvidenceGraphNotConfiguredError):
        await request_graph_extraction(
            db, runtime=dataclasses.replace(runtime, embedding=None), authorized=authorized, product="spring-boot"
        )
    owed = await request_graph_extraction(db, runtime=runtime, authorized=authorized, product="spring-boot",
                                          version="4.0")

    rows = (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry.revision_id).where(
                KnowledgeProjectionOutboxEntry.operation == OUTBOX_OPERATION_EXTRACT_GRAPH
            )
        )
    ).scalars().all()
    assert owed.revisions_owed == 1 and owed.stale_revisions_owed == 0 and rows == [revisions["4.0"]]
