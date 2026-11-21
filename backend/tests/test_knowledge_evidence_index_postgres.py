"""The Evidence index on PostgreSQL (graph on Postgres, part A), on a migrated pgvector server.

The product callers run against :class:`PostgresEvidenceIndexClient`: the ACL marker convergence,
the projector's upsert and delete, the embedding step's vector write, and the query store's
lexical and vector modes. What
these tests pin down is the part only a real server can show:

- the Workspace is the only selector: rows of another Workspace are never returned;
- the ACL marker and the product/version scope are applied inside the statement, so a restricted
  span is invisible to a public request and visible to its principal;
- the lexical fetch matches whole tokens of the ``simple`` parser and ranks before the cap;
- the vector search returns exact cosine neighbours of one space, filtered in the scan;
- deleting a span removes its vectors, and no vector is written for a span that is not projected.

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

from app.services.knowledge.access.acl_keys import PUBLIC_ACL_KEY, RESTRICTED_ACL_KEY
from app.services.knowledge.embedding.catalog import EMBEDDING_SPACES
from app.services.knowledge.embedding.port import EmbeddingPurpose, EmbeddingRuntime
from app.services.knowledge.evidence_index import operations as ops
from app.services.knowledge.evidence_index.errors import EvidenceIndexContractError
from app.services.knowledge.evidence_index.postgres_client import PostgresEvidenceIndexClient
from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.knowledge.ingestion.spans import derive_evidence_key
from app.services.knowledge.retrieval.contracts import RetrievalMode, RetrievalRequest
from app.services.knowledge.retrieval.index_query_store import EvidenceIndexQueryStore
from app.services.knowledge.retrieval.stage_timing import measuring
from tests.alembic_model_parity_support import migrated_database, requires_postgres

pytestmark = requires_postgres

SPACE = EMBEDDING_SPACES["local_mlminilm_384_v1"]
PRINCIPAL = "u." + "a" * 40


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[object]:
    with migrated_database("postgresql", Path(tmp_path_factory.mktemp("evidence-index"))) as migrated:
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


def _unit(index: int) -> list[float]:
    vector = [0.0] * SPACE.dimensions
    vector[index] = 1.0
    return vector


class _FixedEmbedder:
    """Answers one fixed query vector, so the vector mode is deterministic."""

    space = SPACE

    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    async def embed(self, texts: list[str], purpose: EmbeddingPurpose) -> list[list[float]]:
        return [list(self._vector) for _ in texts]


def _run(database, scenario):
    async def main():
        engine = create_async_engine(database.url)
        try:
            client = PostgresEvidenceIndexClient(async_sessionmaker(engine, expire_on_commit=False))
            return await scenario(client)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _upsert(client, workspace, revision, ordinal, body, *, acl=(PUBLIC_ACL_KEY,), products=(), version=""):
    key = derive_evidence_key(revision, ordinal)
    answer = await client.run(
        workspace,
        ops.UPSERT_EVIDENCE_SCOPED,
        {
            "evidence_key": key,
            "body_text": body,
            "revision_id": revision,
            "span_ordinal": ordinal,
            "products": list(products),
            "version": version,
            "acl_keys": list(acl),
        },
    )
    assert answer == ({"count": 1},)
    return key


def test_lexical_mode_is_scoped_by_workspace_acl_and_product(database):
    workspace = WorkspaceId.parse(database.run(_seed_project))
    other = WorkspaceId.parse(database.run(_seed_project))
    revision = str(uuid.uuid4())

    async def scenario(client):
        public = await _upsert(client, workspace, revision, 1, "The billing service retries failed invoices.")
        secret = await _upsert(
            client, workspace, revision, 2, "Invoices of the board are retried by hand.", acl=(RESTRICTED_ACL_KEY, PRINCIPAL)
        )
        scoped = await _upsert(
            client, workspace, revision, 3, "Invoices for the shop product.", products=("shop",), version="2.1"
        )
        await _upsert(client, other, str(uuid.uuid4()), 1, "Invoices of another workspace.")
        # Idempotent: a repeated upsert converges on one row.
        await _upsert(client, workspace, revision, 1, "The billing service retries failed invoices.")
        store = EvidenceIndexQueryStore(client)

        def request(**extra):
            return RetrievalRequest(workspace=workspace, query_text="invoices", modes={RetrievalMode.LEXICAL}, **extra)

        everyone = {e.evidence_id for e in await store.search_lexical(request())}
        reader = {e.evidence_id for e in await store.search_lexical(request(acl_keys=(PUBLIC_ACL_KEY, PRINCIPAL)))}
        shop = {e.evidence_id for e in await store.search_lexical(request(products=("shop",), version="2.1"))}
        count = await client.run(workspace, ops.COUNT_EVIDENCE_BY_KEY, {"evidence_key": public})
        return public, secret, scoped, everyone, reader, shop, count

    public, secret, scoped, everyone, reader, shop, count = _run(database, scenario)
    assert everyone == {public, scoped}
    assert reader == {public, secret, scoped}
    assert shop == {scoped}
    assert count == ({"total": 1},)


def test_lexical_term_matches_whole_tokens_and_query_text_is_data(database):
    workspace = WorkspaceId.parse(database.run(_seed_project))

    async def scenario(client):
        await _upsert(client, workspace, str(uuid.uuid4()), 1, "OwnerRepository finds owners by last name.")
        hits = await client.run(
            workspace, ops.SEARCH_EVIDENCE_LEXICAL, {"term": "owners", "principals": [PUBLIC_ACL_KEY], "cap": 8}
        )
        partial = await client.run(
            workspace, ops.SEARCH_EVIDENCE_LEXICAL, {"term": "own", "principals": [PUBLIC_ACL_KEY], "cap": 8}
        )
        hostile = await client.run(
            workspace,
            ops.SEARCH_EVIDENCE_LEXICAL,
            {"term": "' OR 1=1 -- | !owners & *", "principals": [PUBLIC_ACL_KEY], "cap": 8},
        )
        return hits, partial, hostile

    hits, partial, hostile = _run(database, scenario)
    assert len(hits) == 1
    assert partial == ()
    assert hostile == ()


def test_unmarked_spans_converge_to_public(database):
    project_id = database.run(_seed_project)
    workspace = WorkspaceId.parse(project_id)

    def unmarked(connection: Connection) -> None:
        connection.execute(
            text(
                "INSERT INTO knowledge_evidence_index (project_id, evidence_key, revision_id, span_ordinal, body_text) "
                "VALUES (:p, :k, :r, 1, 'legacy span')"
            ),
            {"p": project_id, "k": derive_evidence_key(str(uuid.uuid4()), 1), "r": str(uuid.uuid4())},
        )

    database.run(unmarked)

    async def scenario(client):
        first = await client.run(workspace, ops.MARK_UNMARKED_EVIDENCE, {"acl_keys": [PUBLIC_ACL_KEY], "cap": 10})
        second = await client.run(workspace, ops.MARK_UNMARKED_EVIDENCE, {"acl_keys": [PUBLIC_ACL_KEY], "cap": 10})
        return first, second

    assert _run(database, scenario) == (({"count": 1},), ({"count": 0},))


def test_vector_mode_returns_exact_neighbours_filtered_in_the_scan(database):
    workspace = WorkspaceId.parse(database.run(_seed_project))
    revision = str(uuid.uuid4())

    async def scenario(client):
        near = await _upsert(client, workspace, revision, 1, "near")
        restricted = await _upsert(client, workspace, revision, 2, "closest but restricted", acl=(RESTRICTED_ACL_KEY,))
        far = await _upsert(client, workspace, revision, 3, "far")
        set_vector = ops.set_vector_operation(SPACE.key)
        query = _unit(0)
        await client.run(workspace, set_vector, {"embedding": [0.9, 0.1] + [0.0] * 382, "evidence_key": near})
        await client.run(workspace, set_vector, {"embedding": query, "evidence_key": restricted})
        await client.run(workspace, set_vector, {"embedding": _unit(1), "evidence_key": far})
        ghost = await client.run(
            workspace, set_vector, {"embedding": query, "evidence_key": derive_evidence_key(revision, 9)}
        )
        stored = await client.run(workspace, ops.read_vector_operation(SPACE.key), {"evidence_key": far})
        store = EvidenceIndexQueryStore(client, embedding=EmbeddingRuntime(space=SPACE, embedder=_FixedEmbedder(query)))
        with measuring() as timer:
            hits = await store.search_vector(
                RetrievalRequest(workspace=workspace, query_text="anything", modes={RetrievalMode.VECTOR}, limit_per_mode=2)
            )
        # The query embedding and the index query are measured apart.
        assert {"embed", "vector_query"} <= set(timer.as_dict())
        await client.run(workspace, ops.DELETE_EVIDENCE, {"evidence_key": far})
        after_delete = await client.run(workspace, ops.read_vector_operation(SPACE.key), {"evidence_key": far})
        return near, far, ghost, stored, hits, after_delete

    near, far, ghost, stored, hits, after_delete = _run(database, scenario)
    assert ghost == ({"count": 0},)
    assert stored[0]["vector"] == _unit(1)
    assert [hit.evidence_id for hit in hits] == [near, far]
    assert hits[0].score == pytest.approx(0.9 / (0.9**2 + 0.1**2) ** 0.5, abs=1e-6)
    assert after_delete == ()


def test_wrong_dimension_and_unregistered_operations_are_refused(database):
    workspace = WorkspaceId.parse(database.run(_seed_project))

    async def scenario(client):
        refused = []
        for key, parameters in (
            (ops.set_vector_operation(SPACE.key), {"embedding": [0.5, 0.5], "evidence_key": "a:1"}),
            ("drop_everything_v1", None),
        ):
            try:
                await client.run(workspace, key, parameters)
            except EvidenceIndexContractError:
                refused.append(key)
        return refused

    assert len(_run(database, scenario)) == 2
