"""Graph expansion in ``knowledge_search``: cited facts behind the hits, one hop, bounded (K3)."""

from __future__ import annotations

import asyncio
import dataclasses
import re

from sqlalchemy import select

from app.models import Project
from app.models.project.knowledge_evidence import KnowledgeEvidenceSpan
from app.models.project.knowledge_source_acl import KnowledgeSourceAcl
from app.models.project.knowledge_temporal import KnowledgeGraphEpisode, KnowledgeGraphWorkspace
from app.models.security.user import UserProject
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.access.bindings import create_binding, revoke_binding
from app.services.knowledge.embedding.catalog import embedding_space
from app.services.knowledge.embedding.port import EmbeddingRuntime
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval import graph_expansion
from app.services.knowledge.temporal import fact_expansion
from app.services.knowledge.temporal.errors import GraphStoreError, GraphStoreState
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context
from tests.knowledge_evidence_text_support import ConceptEmbedder
from tests.knowledge_runtime_support import set_evidence_runtime

LOCAL = embedding_space("local_mlminilm_384_v1")
QUESTION = "Which Java and Spring Framework baseline does Spring Boot 4.0 require?"
_STOP = {"which", "and", "does", "the", "a", "is", "to", "or"}
DOCUMENTS = (
    ("sb-4-migration", "Spring Boot 4.0 Migration Guide", "https://example.com/sb4-migration",
     "## Review System Requirements\n\nSpring Boot 4.0 raises its Java baseline and moves to Jakarta EE 11.\n\n"
     "## Jackson\n\nJackson three arrives with renamed components.\n"),
    ("sb-4-release-notes", "Spring Boot 4.0 Release Notes", "https://example.com/sb4-release-notes",
     "## Dependency Upgrades\n\nNew base for dependency management.\n"),
    ("internal-notes", "Internal gateway notes", "https://example.com/internal", "## Gateway\n\nGateway notes.\n"),
)


def _words(text: str) -> set[str]:
    return {token for token in re.findall(r"\w+", text.lower()) if token not in _STOP}


class FixtureGraph:
    def __init__(self, facts: list[dict], *, delay: float = 0.0, failure: bool = False) -> None:
        self.facts, self.delay, self.failure, self.calls = facts, delay, failure, []

    async def execute_query(self, cypher, **parameters):
        self.calls.append((cypher, parameters))
        if self.failure:
            raise GraphStoreError(GraphStoreState.UNAVAILABLE)
        await asyncio.sleep(self.delay)
        rows = [fact for fact in self.facts if fact["group"] == parameters["group"]]
        if "episodes" in parameters:
            rows = [fact for fact in rows if set(fact["episodes"]) & set(parameters["episodes"])]
        else:
            wanted = set(parameters["entities"])
            rows = [fact for fact in rows if {fact["source_uuid"], fact["target_uuid"]} & wanted]
        return sorted(rows, key=lambda fact: fact["uuid"])[: parameters["limit"]], None, None

    async def close(self):
        pass


def _lexical_edge_search(graph: FixtureGraph, top: int = 3):
    async def ranked(driver, runtime, query, group, limit):
        scored = [(len(_words(fact["fact"]) & _words(query)), fact["uuid"]) for fact in graph.facts
                  if fact["group"] == group]
        return [uuid for score, uuid in sorted(scored, key=lambda item: (-item[0], item[1])) if score][:top]

    return ranked


def _fact(uuid, relation, text, episodes, source, target, group="spring-boot") -> dict:
    return {"uuid": uuid, "relation": relation, "fact": text, "episodes": episodes, "source": source[1],
            "target": target[1], "source_uuid": source[0], "target_uuid": target[0], "group": group,
            "created_at": ""}


SB4, JAVA, JAKARTA, FW7 = ("n-sb4", "Spring Boot 4.0"), ("n-java", "Java 17"), ("n-jee", "Jakarta EE 11"), (
    "n-fw7", "Spring Framework 7")
JSON, GW, BANNER = ("n-json", "@JsonComponent"), ("n-gw", "internal gateway"), ("n-banner", "banner")
FACTS = [
    _fact("f-java", "REQUIRES", "Spring Boot 4.0 requires Java 17 or later", ["ep-req"], SB4, JAVA),
    _fact("f-jakarta", "REQUIRES", "Spring Boot 4.0 is based on Jakarta EE 11", ["ep-req"], SB4, JAKARTA),
    _fact("f-fw7", "REQUIRES", "Spring Boot 4.0 requires Spring Framework 7", ["ep-rel"], SB4, FW7),
    _fact("f-banner", "INTRODUCED", "Spring Boot 4.0 adds a new banner", ["ep-rel"], SB4, BANNER),
    _fact("f-json", "RENAMED", "@JsonComponent has been renamed to @JacksonComponent", ["ep-json"], JSON, JSON),
    _fact("f-gateway", "REQUIRES", "Spring Boot 4.0 requires Java 21 for the internal Framework gateway",
          ["ep-internal"], SB4, GW),
    _fact("f-ship", "REQUIRES", "Spring Boot 4.0 requires Java 17 in the shipping kit", ["ep-ship"], SB4, JAVA, "shipping-protocol"),
]


async def _library(db, name: str = "Spring library"):
    workspace_id = await seed_workspace(db, name=name)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    user = await fetch_user(db, user_id)
    authorized = await authorize_workspace(db, current_user=user, workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime(embedding=EmbeddingRuntime(space=LOCAL, embedder=ConceptEmbedder(LOCAL)))
    set_evidence_runtime(runtime)
    for key, title, url, text in DOCUMENTS:
        await ingest_text_source(db, runtime=runtime, authorized=authorized, source_key=key, display_title=title,
                                 declared_media_type="text/markdown", data=text.encode(), created_by=user_id,
                                 source_url=url, products="spring-boot", version="4.0")
    while await EvidenceProjector(runtime).project_once(db, worker_id="test") is not None:
        pass
    spans = (await db.execute(select(KnowledgeEvidenceSpan.revision_id, KnowledgeEvidenceSpan.span_ordinal,
                                     KnowledgeEvidenceSpan.text).where(
        KnowledgeEvidenceSpan.project_id == workspace_id))).all()
    for episode, marker in (("ep-req", "Java baseline"), ("ep-json", "Jackson three"), ("ep-rel", "New base"),
                            ("ep-internal", "Gateway notes")):
        revision_id, ordinal = next((row[0], row[1]) for row in spans if marker in row[2])
        db.add(KnowledgeGraphEpisode(episode_uuid=episode, project_id=workspace_id, revision_id=revision_id,
                                     span_ordinal=ordinal, group_id="spring-boot",
                                     extraction_profile="change-records-v2"))
    db.add(KnowledgeGraphWorkspace(project_id=workspace_id, embedding_space_key=LOCAL.key))
    db.add(KnowledgeSourceAcl(project_id=workspace_id, source_key="internal-notes", restriction="restricted"))
    await db.commit()
    return runtime, user, authorized, evidence_index


def _use_graph(monkeypatch, graph: FixtureGraph) -> None:
    monkeypatch.setattr(fact_expansion, "PostgresGraphDriver", lambda project_id: graph)
    monkeypatch.setattr(fact_expansion, "ranked_edge_uuids", _lexical_edge_search(graph))


async def _search(db, user, workspace_id: str, query: str = QUESTION, project_ids=None, **params) -> dict:
    context = tool_context(user_id=user.id, project_id=workspace_id, project_ids=project_ids or [workspace_id], db=db)
    return await KnowledgeSearchTool().execute({"query": query, **params}, context)


async def test_the_facts_section_answers_the_baseline_question_with_cited_hit_and_related_facts(db, monkeypatch):
    runtime, user, authorized, _ = await _library(db)
    graph = FixtureGraph(FACTS)
    _use_graph(monkeypatch, graph)

    found = await _search(db, user, authorized.project_id)

    assert found["state"] == "ok" and found["result_count"] >= 1
    section = found["facts"]
    assert section["state"] == "ok" and section["workspace_states"] == {"Spring library": "ok"}
    by_fact = {item["fact"]: item for item in section["facts"]}
    answer = by_fact["Spring Boot 4.0 requires Java 17 or later"]
    assert section["facts"][0] is answer and answer["kind"] == "REQUIRES" and answer["via"] == "hit"
    assert answer["cite_as"] == (
        "[Spring Boot 4.0 Migration Guide § Review System Requirements](https://example.com/sb4-migration)"
    )
    assert answer["source_url"] == "https://example.com/sb4-migration" and answer["version"] == "4.0"
    assert answer["evidence_key"] in {hit["evidence_key"] for hit in found["evidence"]}
    related = by_fact["Spring Boot 4.0 requires Spring Framework 7"]
    assert related["via"] == "related" and related["source_url"] == "https://example.com/sb4-release-notes"
    assert set(by_fact) == {
        "Spring Boot 4.0 requires Java 17 or later",
        "Spring Boot 4.0 is based on Jakarta EE 11",
        "Spring Boot 4.0 requires Spring Framework 7",
    }
    assert [call[1]["limit"] for call in graph.calls] == [fact_expansion.MAX_DIRECT_FACTS, fact_expansion.MAX_HOP_FACTS]
    assert all(call[1]["group"] == "spring-boot" for call in graph.calls)
    assert section["fact_count"] <= graph_expansion.DEFAULT_EXPANSION_FACTS


async def test_the_facts_section_states_why_it_is_empty_and_the_search_still_succeeds(db, monkeypatch):
    runtime, user, authorized, _ = await _library(db)
    workspace_id = authorized.project_id

    _use_graph(monkeypatch, FixtureGraph(FACTS, failure=True))
    found = await _search(db, user, workspace_id)
    assert found["state"] == "ok" and found["evidence"] and found["facts"]["state"] == "unavailable"

    _use_graph(monkeypatch, FixtureGraph(FACTS, delay=1.0))
    monkeypatch.setattr(graph_expansion, "EXPANSION_BUDGET_SECONDS", 0.05)
    found = await _search(db, user, workspace_id)
    assert found["state"] == "ok" and found["facts"]["state"] == "timeout" and found["facts"]["facts"] == []

    assert (await _search(db, user, workspace_id, query="zebra quartz"))["facts"]["state"] == "no_hits"

    set_evidence_runtime(dataclasses.replace(runtime, embedding=None))
    found = await _search(db, user, workspace_id)
    assert found["state"] == "ok" and found["evidence"] and found["facts"]["state"] == "needs_configuration"

    set_evidence_runtime(runtime)
    for episode in (await db.execute(select(KnowledgeGraphEpisode))).scalars().all():
        await db.delete(episode)
    await db.commit()
    found = await _search(db, user, workspace_id)
    assert found["state"] == "ok" and found["facts"] == {
        "state": "not_extracted", "fact_count": 0, "facts_not_shown": 0, "facts": [],
        "workspace_states": {"Spring library": "not_extracted"},
    }


async def test_graph_facts_follow_the_binding_and_its_products_like_the_span_search(db, monkeypatch):
    runtime, user, library, evidence_index = await _library(db)
    _use_graph(monkeypatch, FixtureGraph(FACTS))
    project_id = await seed_workspace(db, name="Acme Orders")
    db.add(UserProject(user_id=user.id, project_id=project_id, role="admin"))
    for workspace_id in (project_id, library.project_id):
        project = await db.get(Project, workspace_id)
        project.config = {**(project.config or {}), "data_policy": {"classification": "internal"}}
    await db.commit()
    reader = await authorize_workspace(db, current_user=user, workspace_id=project_id)
    await ingest_text_source(db, runtime=runtime, authorized=reader, source_key="runbook", display_title="Runbook",
                             declared_media_type="text/markdown", data=b"Our Java baseline runbook.\n",
                             created_by=user.id, products="acme-orders")
    while await EvidenceProjector(runtime).project_once(db, worker_id="test") is not None:
        pass

    binding = await create_binding(db, reader=reader, source_workspace_id=library.project_id,
                                   products=["spring-boot"], reason="library", user=user)
    found = await _search(db, user, project_id, project_ids=[project_id])
    section = found["facts"]
    assert section["state"] == "ok"
    assert section["workspace_states"] == {"Acme Orders": "not_extracted", "Spring library": "ok"}
    assert {item["workspace"] for item in section["facts"]} == {"Spring library"}
    assert "Spring Boot 4.0 requires Java 17 or later" in {item["fact"] for item in section["facts"]}
    outside = await _search(db, user, project_id, project_ids=[project_id], products=["acme-orders"])
    assert outside["facts"]["workspace_states"] == {"Acme Orders": "not_extracted"}

    await revoke_binding(db, workspace=reader, binding_id=binding.id, user=user)
    found = await _search(db, user, project_id, project_ids=[project_id])
    assert found["facts"]["workspace_states"] == {"Acme Orders": "not_extracted"} and found["facts"]["facts"] == []



def test_the_same_statement_from_two_bound_workspaces_is_one_fact():
    from types import SimpleNamespace

    from app.services.knowledge.retrieval.graph_expansion import _fused

    def expanded(text, target="Java 17"):
        fact = SimpleNamespace(relation="REQUIRES", fact=text, source_entity="Spring Boot 4.0", target_entity=target)
        return SimpleNamespace(fact=fact)

    scope = SimpleNamespace(name_of=lambda project_id: project_id)
    answered = [
        ("library", (expanded("Spring Boot 4.0 requires Java 17 or later as a minimum baseline version."),)),
        ("researched", (expanded("Spring Boot 4.0 requires Java 17 or later"), expanded("requires Kotlin 2.2", "Kotlin"))),
    ]
    kept = _fused(scope, answered)
    assert [entry.item.fact.fact for entry in kept] == [
        "Spring Boot 4.0 requires Java 17 or later as a minimum baseline version.",
        "requires Kotlin 2.2",
    ]
