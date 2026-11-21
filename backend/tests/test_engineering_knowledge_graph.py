from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import EngineeringKnowledgeGraphEdge, EngineeringKnowledgeGraphNode
from app.services.engineering_knowledge.graph_store import (
    inspect_engineering_knowledge_entity,
    resolve_engineering_knowledge_alias,
)
from app.services.engineering_knowledge.graph_store_writes import (
    upsert_engineering_knowledge_edge,
    upsert_engineering_knowledge_node,
)
from tests.conftest import ADMIN_PASSWORD


async def _login_admin(client) -> None:
    resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_engineering_knowledge_graph_node_upsert_alias_and_scope_filtering(db):
    source_refs = [
        {
            "source_type": "cicd_finding",
            "source_id": "finding-1",
            "source_uri": "jenkins://acme-orders/build/42",
            "checksum": "sha256:abc",
        }
    ]
    first = await upsert_engineering_knowledge_node(
        db,
        node_type="Library",
        node_key="maven:org.springframework.boot:spring-boot",
        display_name="Spring Boot",
        summary="Spring Boot framework/library coordinate.",
        trust_level="silver",
        classification="internal",
        provenance={"learned_from": "ci-run-42"},
        source_refs=source_refs,
        aliases=[
            {"type": "maven_coordinate", "value": "org.springframework.boot:spring-boot"},
            {"type": "name", "value": "Spring Boot"},
        ],
    )
    await db.flush()
    second = await upsert_engineering_knowledge_node(
        db,
        node_type="library",
        node_key="maven:org.springframework.boot:spring-boot",
        display_name="Spring Boot Framework",
        summary="Updated summary.",
        trust_level="silver",
        classification="internal",
        provenance={"learned_from": "ci-run-43"},
        source_refs=source_refs,
        aliases=[{"type": "name", "value": "Spring Boot"}],
    )
    await db.commit()

    assert second.id == first.id
    count = (
        await db.execute(
            select(func.count()).select_from(EngineeringKnowledgeGraphNode).where(
                EngineeringKnowledgeGraphNode.node_key == "maven:org.springframework.boot:spring-boot"
            )
        )
    ).scalar_one()
    assert count == 1
    resolved = await resolve_engineering_knowledge_alias(db, alias="spring boot", alias_type="name")
    assert resolved is not None
    assert resolved.id == first.id

    project_node = await upsert_engineering_knowledge_node(
        db,
        node_type="library",
        node_key="maven:org.springframework.boot:spring-boot",
        display_name="Spring Boot Acme Orders Override",
        scope_type="project",
        scope_id="acme-orders",
        aliases=[{"type": "name", "value": "Spring Boot"}],
    )
    await db.commit()

    global_entity = await inspect_engineering_knowledge_entity(db, entity_ref="Spring Boot")
    scoped_entity = await inspect_engineering_knowledge_entity(
        db,
        entity_ref="Spring Boot",
        scope_type="project",
        scope_id="acme-orders",
    )
    assert global_entity["id"] == first.id
    assert scoped_entity["id"] == project_node.id
    assert scoped_entity["scope_key"] == "project:acme-orders"


@pytest.mark.asyncio
async def test_engineering_knowledge_graph_edge_upsert_and_related_inspection(db):
    vulnerability = await upsert_engineering_knowledge_node(
        db,
        node_type="vulnerability",
        node_key="CVE-2026-0001",
        display_name="CVE-2026-0001",
        aliases=[{"type": "cve", "value": "CVE-2026-0001"}],
        trust_level="gold",
        source_refs=[{"source_type": "scanner", "source_id": "scan-1"}],
    )
    version = await upsert_engineering_knowledge_node(
        db,
        node_type="version",
        node_key="maven:org.example:demo-lib@2.0.1",
        display_name="demo-lib 2.0.1",
        trust_level="gold",
        source_refs=[{"source_type": "release_notes", "source_uri": "https://example.invalid/demo-lib/2.0.1"}],
    )
    edge = await upsert_engineering_knowledge_edge(
        db,
        edge_type="fixed_by",
        source_node_id=vulnerability.id,
        target_node_id=version.id,
        trust_level="gold",
        classification="internal",
        provenance={"reviewed_by": "security-team"},
        source_refs=[{"source_type": "security_review", "source_id": "review-1"}],
    )
    duplicate = await upsert_engineering_knowledge_edge(
        db,
        edge_type="fixed_by",
        source_node_id=vulnerability.id,
        target_node_id=version.id,
        trust_level="gold",
        classification="internal",
        provenance={"reviewed_by": "security-team"},
        source_refs=[{"source_type": "security_review", "source_id": "review-2"}],
    )
    await db.commit()

    assert duplicate.id == edge.id
    edge_count = (await db.execute(select(func.count()).select_from(EngineeringKnowledgeGraphEdge))).scalar_one()
    assert edge_count == 1
    entity = await inspect_engineering_knowledge_entity(db, entity_ref="CVE-2026-0001")
    assert entity["source_refs"][0]["source_type"] == "scanner"
    assert entity["related_edges"][0]["edge_type"] == "fixed_by"
    assert entity["related_edges"][0]["related_node"]["node_key"] == "maven:org.example:demo-lib@2.0.1"
    assert entity["related_edges"][0]["source_refs"][0]["source_id"] == "review-2"


@pytest.mark.asyncio
async def test_engineering_knowledge_graph_rejects_raw_secret_or_log_payloads(db):
    with pytest.raises(HTTPException) as exc_info:
        await upsert_engineering_knowledge_node(
            db,
            node_type="fix_pattern",
            node_key="unsafe-fix-pattern",
            trust_level="gold",
            properties={"raw_log": "stacktrace with credentials"},
        )
    assert "unsafe raw secret or log field" in str(exc_info.value)

    with pytest.raises(HTTPException) as source_exc:
        await upsert_engineering_knowledge_node(
            db,
            node_type="decision",
            node_key="unsafe-decision",
            source_refs=[{"source_type": "manual", "access_token": "do-not-store"}],
        )
    assert "unsafe raw secret or log field" in str(source_exc.value)


@pytest.mark.asyncio
async def test_engineering_knowledge_graph_admin_api_inspects_entity_with_related_facts(client):
    await _login_admin(client)
    repo_resp = await client.post(
        "/admin/chat/api/panel/engineering-knowledge/graph/nodes",
        json={
            "node_type": "repository",
            "node_key": "bitbucket:acme-orders/backend",
            "display_name": "acme-orders/backend",
            "trust_level": "silver",
            "source_refs": [{"source_type": "bitbucket", "source_id": "repo-acme-orders-backend"}],
            "aliases": [{"type": "repo_slug", "value": "acme-orders-backend"}],
        },
    )
    assert repo_resp.status_code == 200, repo_resp.text
    repo = repo_resp.json()
    pipeline_resp = await client.post(
        "/admin/chat/api/panel/engineering-knowledge/graph/nodes",
        json={
            "node_type": "build_pipeline",
            "node_key": "jenkins:acme-orders-main",
            "display_name": "acme-orders-main",
            "trust_level": "silver",
            "source_refs": [{"source_type": "jenkins", "source_id": "job-acme-orders-main"}],
        },
    )
    assert pipeline_resp.status_code == 200, pipeline_resp.text
    pipeline = pipeline_resp.json()
    edge_resp = await client.post(
        "/admin/chat/api/panel/engineering-knowledge/graph/edges",
        json={
            "edge_type": "verified_by",
            "source_node_id": repo["id"],
            "target_node_id": pipeline["id"],
            "trust_level": "silver",
            "source_refs": [{"source_type": "cicd_trace", "source_id": "trace-1"}],
        },
    )
    assert edge_resp.status_code == 200, edge_resp.text

    inspect_resp = await client.get(
        "/admin/chat/api/panel/engineering-knowledge/graph/entities/acme-orders-backend",
        params={"include_related": "true"},
    )
    assert inspect_resp.status_code == 200, inspect_resp.text
    entity = inspect_resp.json()
    assert entity["id"] == repo["id"]
    assert entity["aliases"][0]["normalized_alias"] == "acme-orders-backend"
    assert entity["related_edges"][0]["edge_type"] == "verified_by"
    assert entity["related_edges"][0]["related_node"]["id"] == pipeline["id"]

    unsafe_resp = await client.post(
        "/admin/chat/api/panel/engineering-knowledge/graph/nodes",
        json={
            "node_type": "policy_finding",
            "node_key": "unsafe-policy-finding",
            "properties": {"password": "not-allowed"},
        },
    )
    assert unsafe_resp.status_code == 400
