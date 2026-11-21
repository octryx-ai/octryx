"""General knowledge graph (tier 2): alias-based identity resolution, ticket
linking, versioned claims, search, and ontology-constrained LLM extraction."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import KnowledgeGraphNode
from app.services.knowledge_graph import (
    add_claim,
    extract_graph_from_text,
    get_claims_for_node,
    get_neighbors,
    ingest_person_identity,
    ingest_ticket_record,
    resolve_node_by_alias,
    search_graph_nodes,
    upsert_node,
)


@pytest.mark.asyncio
async def test_alias_resolution_merges_person_across_sources(db):
    token = uuid.uuid4().hex[:8]
    name = f"Alice Example {token}"
    username = f"alice{token}"

    first = await ingest_person_identity(db, project_id=None, display_name=name, source_ref="confluence:1")
    second = await ingest_person_identity(
        db,
        project_id=None,
        display_name=name,
        usernames=[username],
        emails=[f"{username}@example.com"],
        source_ref="jira:2",
    )
    assert first.id == second.id

    by_username = await resolve_node_by_alias(db, project_id=None, alias=username)
    by_email = await resolve_node_by_alias(db, project_id=None, alias=f"{username}@example.com")
    assert by_username is not None and by_username.id == first.id
    assert by_email is not None and by_email.id == first.id


@pytest.mark.asyncio
async def test_ticket_ingestion_links_person_and_components(db):
    token = uuid.uuid4().hex[:8]
    ticket = {
        "key": f"OCX-{token}",
        "title": "Payment gateway timeout",
        "status": "open",
        "assignee_name": f"Alice Example {token}",
        "assignee_username": f"alice{token}",
        "components": [f"payment-service-{token}", f"billing-{token}"],
    }
    ticket_node = await ingest_ticket_record(db, project_id=None, ticket=ticket)
    neighbors = await get_neighbors(db, node_id=ticket_node.id)
    edge_types = {n["edge_type"] for n in neighbors}
    node_types = {n["node"]["node_type"] for n in neighbors if n["node"]}
    assert "assigned_to" in edge_types
    assert "affects" in edge_types
    assert "person" in node_types
    assert "component" in node_types


@pytest.mark.asyncio
async def test_claims_capture_versioned_facts(db):
    token = uuid.uuid4().hex[:8]
    product = await upsert_node(
        db,
        project_id=None,
        node_type="product",
        node_key=f"foo-{token}",
        display_name=f"Product Foo {token}",
        description="A software product",
    )
    await add_claim(
        db,
        project_id=None,
        subject_node_id=product.id,
        statement="Config X is supported",
        claim_type="config",
        valid_from_label="v4.0",
    )
    claims = await get_claims_for_node(db, node_id=product.id)
    assert len(claims) == 1
    assert claims[0].valid_from_label == "v4.0"


@pytest.mark.asyncio
async def test_graph_search_finds_node(db):
    token = uuid.uuid4().hex[:8]
    await upsert_node(
        db,
        project_id=None,
        node_type="service",
        node_key=f"authsvc-{token}",
        display_name=f"Authentication Service {token}",
        description="Issues oauth tokens and validates sessions",
    )
    results = await search_graph_nodes(db, query=f"Authentication Service {token}", limit=5)
    assert results
    assert any(token in row["display_name"] for row in results)


@pytest.mark.asyncio
async def test_llm_extraction_respects_ontology(db):
    token = uuid.uuid4().hex[:8]

    async def fake_generate(_prompt: str) -> str:
        return (
            '{"entities": ['
            f'{{"name": "Billing Service {token}", "type": "service", "description": "handles invoices"}},'
            f'{{"name": "Payment Gateway {token}", "type": "service", "description": "stripe integration"}},'
            f'{{"name": "Alien Thing {token}", "type": "alien", "description": "disallowed type"}}'
            '], "relations": ['
            f'{{"source": "Billing Service {token}", "target": "Payment Gateway {token}", '
            '"type": "depends_on", "description": "uses it"}]}'
        )

    result = await extract_graph_from_text(
        db,
        project_id=None,
        text="Billing depends on the payment gateway.",
        source_ref=f"doc:{token}",
        generate=fake_generate,
    )
    assert result["entities"] == 2  # the disallowed "alien" type is dropped
    assert result["relations"] == 1

    rows = (
        (await db.execute(select(KnowledgeGraphNode).where(KnowledgeGraphNode.node_key.like(f"%{token}%"))))
        .scalars()
        .all()
    )
    assert all(row.node_type == "service" for row in rows)


@pytest.mark.asyncio
async def test_multi_source_evidence_promotes_node_and_edge_to_silver(db):
    token = uuid.uuid4().hex[:8]
    node = await upsert_node(
        db,
        project_id=None,
        node_type="service",
        node_key=f"svc-{token}",
        display_name=f"Service {token}",
        source_refs=[f"km:src-a-{token}"],
        embed=False,
    )
    assert node.trust_level == "bronze"
    node = await upsert_node(
        db,
        project_id=None,
        node_type="service",
        node_key=f"svc-{token}",
        source_refs=[f"km:src-b-{token}"],
        embed=False,
    )
    assert node.trust_level == "silver"  # two distinct sources confirm it

    other = await upsert_node(
        db, project_id=None, node_type="service", node_key=f"dep-{token}", embed=False
    )
    from app.services.knowledge_graph import upsert_edge

    edge = await upsert_edge(
        db,
        project_id=None,
        edge_type="depends_on",
        source_node_id=node.id,
        target_node_id=other.id,
        source_refs=[f"km:src-a-{token}"],
        embed=False,
    )
    assert edge.trust_level == "bronze"
    edge = await upsert_edge(
        db,
        project_id=None,
        edge_type="depends_on",
        source_node_id=node.id,
        target_node_id=other.id,
        source_refs=[f"km:src-b-{token}"],
        embed=False,
    )
    assert edge.trust_level == "silver"

    neighbors = await get_neighbors(db, node_id=node.id)
    dep = next(item for item in neighbors if (item.get("node") or {}).get("id") == other.id)
    assert dep["trust_level"] == "silver"
    assert dep["evidence_count"] == 2


def test_evidence_trust_level_never_demotes_explicit_levels():
    from app.services.knowledge_trust import evidence_trust_level

    assert evidence_trust_level("bronze", ["km:a"]) == "bronze"
    assert evidence_trust_level("bronze", ["km:a", "km:b"]) == "silver"
    assert evidence_trust_level("silver", []) == "silver"
    assert evidence_trust_level("gold", ["km:a"]) == "gold"
    assert evidence_trust_level("federated", []) == "federated"
    assert evidence_trust_level("", []) == "bronze"
