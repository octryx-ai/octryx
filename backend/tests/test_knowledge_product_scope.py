"""Product and version scope: labels inside one Workspace that narrow retrieval.

Three sources share one Workspace: Spring Boot 4.0 and 3.5 migration notes and a Acme Orders runbook.
Narrowing happens inside the index statement (the fake mirrors the statements), so a hit
of another product never reaches the ledger resolution at all.
"""

from __future__ import annotations

import pytest

from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.embedding.catalog import embedding_space
from app.services.knowledge.embedding.port import EmbeddingRuntime
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.ledger.queries import workspace_products
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import LEXICAL_MODES, VECTOR_MODES, retrieve_workspace_evidence
from app.services.knowledge.retrieval.hybrid import hybrid_workspace_evidence
from app.services.knowledge.runtime import set_evidence_runtime
from app.services.knowledge.sources.scope import normalize_products, normalize_version
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context
from tests.knowledge_evidence_text_support import ConceptEmbedder

LOCAL = embedding_space("local_mlminilm_384_v1")
SOURCES = (
    ("boot4", "Spring Boot 4.0 migration: the failover exercise config moved.\n", "spring-boot", "4.0"),
    ("boot35", "Spring Boot 3.5 migration: the failover exercise config stays.\n", "spring-boot", "3.5"),
    ("risk", "Acme Orders migration runbook: the failover exercise happens weekly.\n", "acme-orders", None),
)



async def _workspace(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime(embedding=EmbeddingRuntime(space=LOCAL, embedder=ConceptEmbedder(LOCAL)))
    for key, text, product, version in SOURCES:
        await ingest_text_source(
            db,
            runtime=runtime,
            authorized=authorized,
            source_key=key,
            display_title=key,
            declared_media_type="text/markdown",
            data=text.encode(),
            created_by=user_id,
            products=product,
            version=version,
        )
    projector = EvidenceProjector(runtime)
    while await projector.project_once(db, worker_id="test") is not None:
        pass
    return workspace_id, user_id, authorized, runtime


def test_scope_values_are_validated_not_cleaned_up() -> None:
    assert normalize_products("Spring-Boot, acme-orders,spring-boot") == ("spring-boot", "acme-orders")
    assert normalize_products(None) == () and normalize_version(" 4.0 ") == "4.0"
    for bad in ("spring boot", "a" * 41, ",".join(f"p{i}" for i in range(9)), 5):
        with pytest.raises(InvalidEvidenceRequestError):
            normalize_products(bad)
    with pytest.raises(InvalidEvidenceRequestError):
        normalize_version("4.0; drop")


async def test_lexical_and_vector_search_narrow_to_the_product_and_version(db) -> None:
    _, _, authorized, runtime = await _workspace(db)

    async def titles(modes, **scope):
        result = await retrieve_workspace_evidence(
            db, runtime=runtime, authorized=authorized, query_text="migration failover", modes=modes, **scope
        )
        return sorted(item.revision_id and item.citation.split(" (")[0] for item in result.evidence)

    for modes in (LEXICAL_MODES, VECTOR_MODES):
        assert await titles(modes) == ["boot35", "boot4", "risk"]
        assert await titles(modes, products=["spring-boot"]) == ["boot35", "boot4"]
        assert await titles(modes, products=["spring-boot"], version="4.0") == ["boot4"]
        assert await titles(modes, products=["acme-orders"]) == ["risk"]
    with pytest.raises(InvalidEvidenceRequestError):
        await titles(LEXICAL_MODES, version="4.0")  # a version belongs to a product


async def test_hits_carry_their_scope_and_the_workspace_lists_its_products(db) -> None:
    _, _, authorized, runtime = await _workspace(db)

    fused = await hybrid_workspace_evidence(
        db, runtime=runtime, authorized=authorized, query_text="migration", products=["spring-boot"], version="4.0"
    )

    assert [(hit.evidence.products, hit.evidence.version) for hit in fused.evidence] == [(("spring-boot",), "4.0")]
    assert await workspace_products(db, authorized) == {"acme-orders": [""], "spring-boot": ["3.5", "4.0"]}


async def test_the_tool_narrows_on_request_and_refuses_a_malformed_product(db) -> None:
    workspace_id, user_id, _, runtime = await _workspace(db)
    context = tool_context(user_id=user_id, project_id=workspace_id, project_ids=[workspace_id], db=db)
    set_evidence_runtime(runtime)
    try:
        narrowed = await KnowledgeSearchTool().execute(
            {"query": "migration", "products": ["acme-orders"]}, context
        )
        refused = await KnowledgeSearchTool().execute(
            {"query": "migration", "products": ["Acme Orders"]}, context
        )
    finally:
        set_evidence_runtime(None)

    assert [hit["products"] for hit in narrowed["evidence"]] == [["acme-orders"]]
    assert refused["state"] == "invalid_request"
