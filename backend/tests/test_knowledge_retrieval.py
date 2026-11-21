"""Hybrid retrieval: chunks (tier 1) + graph entities/relations (tier 2)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.knowledge_chunking import index_source_chunks
from app.services.knowledge_graph import ingest_ticket_record
from app.services.knowledge_retrieval import (
    MODE_LOCAL,
    MODE_NAIVE,
    build_context_block,
    retrieve_knowledge,
)


async def _project_id(db) -> str:
    project = (await db.execute(select(Project))).scalars().first()
    assert project is not None
    return project.id


@pytest.mark.asyncio
async def test_mix_retrieval_combines_chunks_and_graph(db):
    token = uuid.uuid4().hex[:8]
    project_id = await _project_id(db)
    await index_source_chunks(
        db,
        project_id=project_id,
        source_ref=f"doc-{token}",
        text=f"The orders service {token} handles checkout and talks to the payment gateway.",
    )
    await ingest_ticket_record(
        db,
        project_id=project_id,
        ticket={
            "key": f"OCX-{token}",
            "title": f"orders service {token} latency",
            "assignee_name": f"Alice Example {token}",
            "assignee_username": f"alice{token}",
            "components": [f"orders-service-{token}"],
        },
    )

    result = await retrieve_knowledge(db, query=f"orders service {token}", project_ids=[project_id])
    assert result["mode"] == "mix"
    assert result["chunks"], "expected chunk recall"
    assert result["entities"], "expected graph entities"
    assert any(r.get("edge_type") for r in result["relations"])

    block = build_context_block(result)
    assert "Entities:" in block or "Passages:" in block
    assert token in block


@pytest.mark.asyncio
async def test_naive_mode_is_chunks_only(db):
    token = uuid.uuid4().hex[:8]
    project_id = await _project_id(db)
    await index_source_chunks(
        db,
        project_id=project_id,
        source_ref=f"doc-naive-{token}",
        text=f"authentication service {token} issues tokens.",
    )
    result = await retrieve_knowledge(
        db, query=f"authentication service {token}", project_ids=[project_id], mode=MODE_NAIVE
    )
    assert result["chunks"]
    assert result["entities"] == []


@pytest.mark.asyncio
async def test_local_mode_is_graph_only(db):
    token = uuid.uuid4().hex[:8]
    project_id = await _project_id(db)
    await ingest_ticket_record(
        db,
        project_id=project_id,
        ticket={"key": f"OCX-L{token}", "title": f"billing service {token}", "components": [f"billing-{token}"]},
    )
    result = await retrieve_knowledge(
        db, query=f"billing service {token}", project_ids=[project_id], mode=MODE_LOCAL
    )
    assert result["chunks"] == []
    assert result["entities"]


@pytest.mark.asyncio
async def test_alias_query_pins_exact_identifiers_dropped_by_keyword_rewrite(db):
    """Entity linking must see the ORIGINAL question: when the keyword rewrite
    drops an exact identifier (a file name like report-builder.py), the alias match
    still pins its node."""
    from app.services.knowledge_graph import ingest_code_structure
    from app.services.knowledge_graph.retrieval import search_graph_nodes

    token = uuid.uuid4().hex[:8]
    await ingest_code_structure(
        db,
        project_id=None,
        snapshot={
            "repository": f"repo-{token}",
            "modules": [
                {"path": f"tools/report-builder-{token}.py", "name": f"report-builder-{token}.py", "imports": []}
            ],
        },
    )
    # Simulate a keyword rewrite that lost the identifier entirely.
    nodes = await search_graph_nodes(
        db,
        query="weekly summary tooling",
        alias_query=f"What does report-builder-{token}.py do?",
        limit=5,
    )
    names = [n["display_name"] for n in nodes]
    assert f"report-builder-{token}.py" in names
