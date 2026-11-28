"""LightRAG/GraphRAG quality parity: description merge, gleaning, claims,
dual-level retrieval (keywords + relation search), provenance, global synthesis."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.knowledge_chunking import index_source_chunks
from app.services.knowledge_graph import (
    build_communities,
    extract_graph_from_text,
    extract_query_keywords,
    global_search,
    ingest_ticket_record,
    merge_descriptions,
    search_graph_edges,
    upsert_node,
)
from app.services.knowledge_retrieval import build_context_block, retrieve_knowledge


async def _project_id(db) -> str:
    project = (await db.execute(select(Project))).scalars().first()
    assert project is not None
    return project.id


def test_merge_descriptions_accumulates_instead_of_overwriting():
    merged = merge_descriptions("Runs the checkout flow.", "Owned by the payments team.")
    assert "checkout" in merged and "payments team" in merged
    # Duplicate fragments are not appended twice.
    again = merge_descriptions(merged, "Owned by the payments team.")
    assert again == merged
    # Cap holds.
    long = merge_descriptions("x" * 3000, "new fact")
    assert len(long) <= 2400


@pytest.mark.asyncio
async def test_upsert_node_merges_descriptions_across_sources(db):
    token = uuid.uuid4().hex[:8]
    first = await upsert_node(
        db, project_id=None, node_type="service", node_key=f"merge-{token}",
        display_name=f"Orders {token}", description="Handles checkout.", embed=False,
    )
    second = await upsert_node(
        db, project_id=None, node_type="service", node_key=f"merge-{token}",
        display_name=f"Orders {token}", description="Deployed on EKS.", embed=False,
    )
    assert first.id == second.id
    assert "checkout" in second.description.lower()
    assert "eks" in second.description.lower()


@pytest.mark.asyncio
async def test_gleaning_second_pass_adds_missed_entities(db):
    token = uuid.uuid4().hex[:8]
    calls = {"n": 0}

    async def fake_generate(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return (
                '{"entities": [{"name": "Billing ' + token + '", "type": "service", '
                '"description": "handles invoices"}], "relations": [], "claims": []}'
            )
        # Gleaning pass finds a missed entity + relation.
        return (
            '{"entities": [{"name": "Ledger ' + token + '", "type": "service", '
            '"description": "stores postings"}], '
            '"relations": [{"source": "Billing ' + token + '", "target": "Ledger ' + token + '", '
            '"type": "depends_on", "description": "posts to"}], "claims": []}'
        )

    result = await extract_graph_from_text(
        db, project_id=None, text="Billing posts to the ledger.",
        source_ref=f"doc:{token}", generate=fake_generate, gleaning_rounds=2,
    )
    assert result["entities"] == 2
    assert result["relations"] == 1
    assert calls["n"] >= 2  # extraction + at least one gleaning round ran


@pytest.mark.asyncio
async def test_claims_are_extracted_and_appear_as_facts(db):
    token = uuid.uuid4().hex[:8]
    project_id = await _project_id(db)

    async def fake_generate(prompt: str) -> str:
        if "MISSED" in prompt:
            return '{"entities": [], "relations": [], "claims": []}'
        return (
            '{"entities": [{"name": "Product Foo ' + token + '", "type": "product", '
            '"description": "vendor software"}], "relations": [], '
            '"claims": [{"subject": "Product Foo ' + token + '", '
            '"statement": "Config X is supported", "type": "config", '
            '"valid_from": "v4.0", "valid_until": null}]}'
        )

    result = await extract_graph_from_text(
        db, project_id=project_id, text="Since v4.0 Product Foo supports Config X.",
        source_ref=f"doc:{token}", generate=fake_generate, gleaning_rounds=1,
    )
    assert result["claims"] == 1

    retrieved = await retrieve_knowledge(
        db, query=f"Product Foo {token}", project_ids=[project_id], mode="local"
    )
    assert retrieved["facts"], "expected the claim to surface as a fact"
    fact = retrieved["facts"][0]
    assert fact["valid_from"] == "v4.0"
    block = build_context_block(retrieved)
    assert "Facts:" in block and "v4.0" in block


@pytest.mark.asyncio
async def test_query_keywords_deterministic_without_tagged_runtime(db):
    keywords = await extract_query_keywords(db, query="who is Alice Example in the payment system")
    assert keywords.source == "deterministic"
    assert "Alice" in keywords.low_level or "alice" in [k.lower() for k in keywords.low_level]


@pytest.mark.asyncio
async def test_relation_search_finds_edges_by_theme(db):
    token = uuid.uuid4().hex[:8]
    project_id = await _project_id(db)
    await ingest_ticket_record(
        db,
        project_id=project_id,
        ticket={
            "key": f"OCX-E{token}",
            "title": f"checkout latency {token}",
            "assignee_name": f"Dev {token}",
            "components": [f"checkout-{token}"],
        },
    )
    edges = await search_graph_edges(db, query=f"checkout latency {token}", project_ids=[project_id])
    assert edges, "expected the affects/assigned_to edges to be findable"
    assert any(edge["edge_type"] in {"affects", "assigned_to"} for edge in edges)


@pytest.mark.asyncio
async def test_provenance_chunks_join_entity_results(db):
    token = uuid.uuid4().hex[:8]
    project_id = await _project_id(db)
    # A chunked source document and an entity whose source_refs point at it.
    source_ref = f"km:prov-{token}"
    await index_source_chunks(
        db, project_id=project_id, source_ref=source_ref,
        text=f"The inventory service {token} reconciles stock nightly.",
    )
    await upsert_node(
        db, project_id=project_id, node_type="service", node_key=f"inv-{token}",
        display_name=f"Inventory Service {token}",
        description="Reconciles stock levels",
        source_refs=[source_ref],
    )
    result = await retrieve_knowledge(
        db, query=f"Inventory Service {token}", project_ids=[project_id], mode="local"
    )
    assert result["entities"]
    provenance = [chunk for chunk in result["chunks"] if chunk.get("provenance") == "entity_source"]
    assert provenance, "expected the entity's own source chunks as evidence"
    assert token in provenance[0]["text"]


@pytest.mark.asyncio
async def test_global_search_synthesizes_over_community_reports(db):
    token = uuid.uuid4().hex[:8]
    project_id = await _project_id(db)
    await ingest_ticket_record(
        db,
        project_id=project_id,
        ticket={"key": f"OCX-G{token}", "title": f"payments outage {token}", "components": [f"payments-{token}"]},
    )
    await build_communities(db, project_id=project_id)

    async def fake_generate(prompt: str) -> str:
        assert "Community reports" in prompt
        return f"The payments {token} area handles outage work [1]."

    synthesis = await global_search(
        db, query=f"payments {token}", generate=fake_generate, project_ids=[project_id]
    )
    assert synthesis["candidates"] >= 1
    assert token in synthesis["answer"]
    assert synthesis["communities_used"]
