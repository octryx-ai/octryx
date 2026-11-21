"""Change-record typing v2: the typed self-check, the profile migration, and re-extraction on request.

Contract tests only. Whether the model types a sentence correctly is measured with the real governed
model by the opt-in ``app.services.knowledge.eval.change_typing`` script, never here:

- Graphiti's real fact extraction, through the governed client, asks for the self-checked answer
  and stores a fact the self-check denies without a change type;
- a request owes the version range and every revision of the product still holding an earlier
  profile, and the status shows what is stale.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.project.knowledge_evidence import OUTBOX_OPERATION_EXTRACT_GRAPH, KnowledgeProjectionOutboxEntry
from app.models.project.knowledge_temporal import KnowledgeGraphEpisode
from app.services.content_security.model_call_scope import session_call
from app.services.knowledge.eval import change_typing
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.temporal.change_self_check import EDGE_PROMPT
from app.services.knowledge.temporal.change_types import (
    CHANGE_EDGE_TYPES,
    CHANGE_RECORDS_PROFILE,
    CURRENT_PROFILES,
    NOT_A_CHANGE_RELATION,
)
from app.services.knowledge.temporal.errors import GraphStoreError
from app.services.knowledge.temporal.extraction_requests import graph_status, request_graph_extraction
from app.services.knowledge.temporal.graphiti_adapters import RefusingCrossEncoder
from app.services.knowledge.temporal.graphiti_boundary import (
    EntityNode,
    EpisodeType,
    EpisodicNode,
    ExtractedEdges,
    GraphitiClients,
    NoOpTracer,
    extract_edges,
)
from app.services.knowledge.temporal.graphiti_llm import GovernedGraphitiLLM
from tests.test_knowledge_temporal_graph import _library

STALE = "change-records-v1"


class _Provider:
    """A provider client answering Graphiti's fact prompt with a fixed, self-checked answer."""

    def __init__(self, seen: list[str]) -> None:
        self._seen = seen

    async def chat(self, *, messages, **options):
        self._seen.append(messages[-1]["content"])
        edge = {"source_entity_name": "Spring Boot 4.0", "valid_at": None, "invalid_at": None}
        answer = {
            "edges": [
                {**edge, "target_entity_name": "Java 17", "relation_type": "REQUIRES",
                 "fact": "Spring Boot 4.0 requires Java 17", "states_version_change": True},
                {**edge, "target_entity_name": "Observation API", "relation_type": "REQUIRES",
                 "fact": "Tracing operates on the Observation API", "states_version_change": False},
                {**edge, "target_entity_name": "spring.http.clients", "relation_type": "replaced_by",
                 "fact": "spring.http.client is replaced by spring.http.clients", "states_version_change": True},
                {**edge, "target_entity_name": "Observation API", "relation_type": "PROVIDES",
                 "fact": "Spring Boot 4.0 provides the Observation API", "states_version_change": False},
            ]
        }
        return {"content": json.dumps(answer), "usage": {"input_tokens": 10, "output_tokens": 5}}


async def test_a_fact_the_self_check_denies_is_stored_without_a_change_type(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr("app.agent.providers.get_provider", lambda **runtime: _Provider(seen))
    llm = GovernedGraphitiLLM([{"provider_name": "fake", "model": "m"}], scope=session_call(None), check_change_edges=True)
    clients = GraphitiClients(
        driver=change_typing._NoGraph(), llm_client=llm, embedder=change_typing._NoEmbedder(),
        cross_encoder=RefusingCrossEncoder(), tracer=NoOpTracer(),
    )
    now = datetime.now(UTC)
    episode = EpisodicNode(name="s", group_id="spring-boot", labels=[], source=EpisodeType.text,
                           source_description="spring-boot 4.0", content="…", created_at=now, valid_at=now)
    nodes = [EntityNode(name=name, group_id="spring-boot", labels=["Entity"], created_at=now)
             for name in ("Spring Boot 4.0", "Java 17", "Observation API", "spring.http.clients")]

    edges = await extract_edges(clients, episode, nodes, [], {("Entity", "Entity"): list(CHANGE_EDGE_TYPES)},
                                "spring-boot", CHANGE_EDGE_TYPES, "instructions")

    assert [edge.name for edge in edges] == ["REQUIRES", NOT_A_CHANGE_RELATION, "REPLACED_BY", "PROVIDES"]
    assert llm.usage.demoted == 1 and "states_version_change" in seen[0]
    # Graphiti's own schema for every other prompt; a changed fact-prompt contract is refused.
    with pytest.raises(GraphStoreError):
        await llm.generate_response([], response_model=EntityNode, prompt_name=EDGE_PROMPT)
    unchecked = GovernedGraphitiLLM([{"provider_name": "fake", "model": "m"}], scope=session_call(None))
    seen.clear()
    await unchecked.generate_response(
        [SimpleNamespace(role="user", content="x")], response_model=ExtractedEdges, prompt_name=EDGE_PROMPT
    )
    assert "states_version_change" not in seen[0]


def test_the_profile_is_versioned_and_the_golden_set_uses_only_the_closed_types():
    assert CHANGE_RECORDS_PROFILE == "change-records-v2" and STALE not in CURRENT_PROFILES
    golden = change_typing.load_typing_golden("change_typing_spring_boot")
    labels = {item.expected for item in golden.sentences}
    assert len(golden.sentences) >= 20 and labels == set(CHANGE_EDGE_TYPES) | {change_typing.NONE}
    perfect = {item.id: set() if item.expected == change_typing.NONE else {item.expected} for item in golden.sentences}
    report = change_typing.score(golden, perfect)
    assert report["exact_sentences"] == len(golden.sentences) and not report["none_typed_as_change"]
    assert {entry["precision"] for entry in report["per_type"].values()} == {1.0}


def _episode(authorized, revision_id: str, uuid: str, profile: str) -> KnowledgeGraphEpisode:
    return KnowledgeGraphEpisode(episode_uuid=uuid, project_id=authorized.project_id, revision_id=revision_id,
                                 span_ordinal=1, group_id="spring-boot", extraction_profile=profile)


async def test_a_request_owes_the_range_and_every_revision_still_holding_an_earlier_profile(db):
    authorized, runtime, revisions = await _library(db)
    db.add(_episode(authorized, revisions["3.5"], "ep-35", STALE))
    await db.commit()

    for bad in ({"version": "4.0", "to_version": "4.1"}, {"from_version": "4.1", "to_version": "4.0"},
                {"from_version": "3.5"}):
        with pytest.raises(InvalidEvidenceRequestError):
            await request_graph_extraction(db, runtime=runtime, authorized=authorized, product="spring-boot", **bad)
    owed = await request_graph_extraction(db, runtime=runtime, authorized=authorized, product="spring-boot",
                                          from_version="3.5", to_version="4.1")
    status = await graph_status(db, authorized.project_id)

    rows = (await db.execute(select(KnowledgeProjectionOutboxEntry.revision_id).where(
        KnowledgeProjectionOutboxEntry.operation == OUTBOX_OPERATION_EXTRACT_GRAPH))).scalars().all()
    # 4.0 and 4.1 are the range; 3.5 is outside it but holds an earlier profile.
    assert (owed.revisions_owed, owed.stale_revisions_owed) == (3, 1) and set(rows) == set(revisions.values())
    assert status.profiles == {STALE: 1} and status.stale_episodes == 1 and status.pending_revisions == 3
