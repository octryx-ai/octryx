"""A5: ``similar_to`` between sections of different manuals from stored vectors, bounded and cited."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.models.project.knowledge_evidence import KnowledgeWorkspaceVectorSpace
from app.models.project.knowledge_structured import KnowledgeStructuredEdge
from app.services.knowledge.access.authorization import parse_workspace_id
from app.services.knowledge.embedding.catalog import embedding_space
from app.services.knowledge.evidence_index.errors import EvidenceIndexUnavailableError
from app.services.knowledge.evidence_index.operations import SEARCH_EVIDENCE_VECTOR, operation, read_vector_operation
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import TRIGGER_MANUAL
from app.services.knowledge.structured.facts import node_id
from app.services.knowledge.structured.layers import BuildContext
from app.services.knowledge.structured.profile import structured_profile
from app.services.knowledge.structured.similarity import link_similar_sections
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.services.knowledge.structured.structured_graph_support import (
    CONSOLE_MANUAL,
    SERVER_MANUAL,
    seed_parsed_revision,
)

SPACE = embedding_space("local_mlminilm_384_v1")


class FakeVectors:
    def __init__(self, neighbours: dict[str, list[tuple[str, float]]], *, failing: bool = False) -> None:
        self.neighbours, self.failing, self.calls = neighbours, failing, []

    async def run(self, workspace, key, parameters):
        self.calls.append((key, parameters))
        if self.failing:
            raise EvidenceIndexUnavailableError()
        if key == read_vector_operation(SPACE.key):
            return ({"vector": [float(len(self.calls)), 1.0]},) if parameters["evidence_key"] in self.neighbours else ()
        assert key == SEARCH_EVIDENCE_VECTOR
        source = next(evidence for evidence in self.neighbours if self.calls[-2][1]["evidence_key"] == evidence)
        return tuple({"evidence_key": hit, "distance": distance} for hit, distance in self.neighbours[source])


def _key(revision_id: str, ordinal: int) -> str:
    return f"{uuid.UUID(revision_id).hex}:{ordinal}"


async def _two_manuals(db):
    project_id = await seed_workspace(db)
    _, server = await seed_parsed_revision(db, project_id, source_key="server", title="Server", spans=SERVER_MANUAL)
    _, app = await seed_parsed_revision(db, project_id, source_key="app", title="App", spans=CONSOLE_MANUAL)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    await claim_next_build(db, worker_id="w")
    await run_build_slice(db, runtime=None, build_id=build.id, worker_id="w")
    db.add(KnowledgeWorkspaceVectorSpace(project_id=project_id, space_key=SPACE.key))
    await db.commit()
    return project_id, server, app


def _context(db, project_id, vectors):
    runtime = SimpleNamespace(embedding=SimpleNamespace(space=SPACE), runtime_client=vectors)
    return BuildContext(db, runtime, parse_workspace_id(project_id), project_id, structured_profile())


async def _similar(db, project_id):
    rows = await db.execute(select(KnowledgeStructuredEdge).where(
        KnowledgeStructuredEdge.project_id == project_id, KnowledgeStructuredEdge.edge_type == "similar_to"))
    return rows.scalars().all()


async def test_sections_of_different_manuals_link_above_the_threshold_with_both_citations(db):
    project_id, server, app = await _two_manuals(db)
    vectors = FakeVectors({
        _key(server, 8): [(_key(app, 3), 0.08), (_key(app, 1), 0.5), (_key(server, 9), 0.0)],
    })
    result = await link_similar_sections(_context(db, project_id, vectors))
    assert result["state"] == "ok" and result["edges"] == 1 and result["added"] == 1
    (edge,) = await _similar(db, project_id)
    pair = {node_id("Subsection", "server#6.3.3"), node_id("Section", "app#3.2")}
    assert {edge.source_id, edge.target_id} == pair and edge.revision_id is None
    assert edge.properties == {"score": 0.92}
    assert sorted(map(tuple, edge.citations)) == sorted([(server, 8, None), (app, 3, None)])
    searches = [parameters for key, parameters in vectors.calls if key == SEARCH_EVIDENCE_VECTOR]
    assert searches and all(parameters["principals"] == ["public"] for parameters in searches)


async def test_relinking_is_idempotent_and_a_store_failure_keeps_the_edges(db):
    project_id, server, app = await _two_manuals(db)
    vectors = FakeVectors({_key(server, 8): [(_key(app, 3), 0.05)]})
    await link_similar_sections(_context(db, project_id, vectors))
    again = await link_similar_sections(_context(db, project_id, vectors))
    assert again["added"] == 0 and again["removed"] == 0
    failed = await link_similar_sections(_context(db, project_id, FakeVectors({}, failing=True)))
    assert failed == {"state": "unavailable"} and len(await _similar(db, project_id)) == 1
    gone = await link_similar_sections(_context(db, project_id, FakeVectors({})))
    assert gone["removed"] == 1 and not await _similar(db, project_id)


async def test_without_vectors_in_the_workspace_similarity_needs_configuration(db):
    project_id = await seed_workspace(db)
    result = await link_similar_sections(_context(db, project_id, FakeVectors({})))
    assert result == {"state": "needs_configuration"}


def test_the_read_vector_operation_is_registered_per_space():
    spec = operation(read_vector_operation(SPACE.key))
    assert spec.parameters == frozenset({"evidence_key"})
