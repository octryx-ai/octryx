"""Chunking + incremental indexing + chunk retrieval (naive vector-RAG tier)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import KnowledgeChunk, Project
from app.services.knowledge_chunking import (
    chunk_document,
    index_source_chunks,
    search_knowledge_chunks,
)


def test_chunker_is_deterministic_and_indexed():
    text = "\n\n".join(f"Paragraph {i} about payment services and refunds and invoices." for i in range(20))
    first = chunk_document(text, max_tokens=40, overlap_tokens=8)
    second = chunk_document(text, max_tokens=40, overlap_tokens=8)
    assert [c.text for c in first] == [c.text for c in second]
    assert len(first) > 1
    assert [c.index for c in first] == list(range(len(first)))


def test_chunker_handles_empty_text():
    assert chunk_document("") == []
    assert chunk_document("   \n   \n ") == []


@pytest.mark.asyncio
async def test_indexing_is_incremental(db):
    project = (await db.execute(select(Project))).scalars().first()
    assert project is not None
    ref = f"chunk-test-{uuid.uuid4()}"
    text = "\n\n".join(f"Section {i}: the deployment runs on the kubernetes prod cluster." for i in range(6))

    first = await index_source_chunks(db, project_id=project.id, source_ref=ref, text=text)
    assert first["created"] >= 1
    assert first["total_chunks"] == first["created"]

    # Re-indexing identical text changes nothing.
    again = await index_source_chunks(db, project_id=project.id, source_ref=ref, text=text)
    assert again["created"] == 0
    assert again["updated"] == 0
    assert again["unchanged"] == first["created"]

    # Default embedding provider (local_hash) populates vectors.
    rows = (
        (await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.source_ref == ref))).scalars().all()
    )
    assert rows
    assert all(isinstance(row.embedding, list) and row.embedding for row in rows)


@pytest.mark.asyncio
async def test_changed_text_updates_and_prunes(db):
    project = (await db.execute(select(Project))).scalars().first()
    ref = f"chunk-change-{uuid.uuid4()}"
    long_text = "\n\n".join(
        f"Item {i}: alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november."
        for i in range(60)
    )
    first = await index_source_chunks(db, project_id=project.id, source_ref=ref, text=long_text, source_kind="document")
    assert first["total_chunks"] > 1  # large text spans multiple chunks

    shorter = "Item 0: alpha bravo charlie delta echo foxtrot golf."
    result = await index_source_chunks(db, project_id=project.id, source_ref=ref, text=shorter)
    # Fewer chunks now → some old chunks are deleted.
    assert result["deleted"] >= 1
    remaining = (
        (await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.source_ref == ref))).scalars().all()
    )
    assert len(remaining) == result["total_chunks"]


@pytest.mark.asyncio
async def test_search_finds_relevant_chunk(db):
    project = (await db.execute(select(Project))).scalars().first()
    ref = f"chunk-search-{uuid.uuid4()}"
    text = (
        "The billing service handles invoices.\n\n"
        "The authentication service issues tokens via oauth.\n\n"
        "The payment gateway integrates with stripe."
    )
    await index_source_chunks(db, project_id=project.id, source_ref=ref, text=text)

    results = await search_knowledge_chunks(db, query="oauth tokens", project_ids=[project.id], limit=5)
    assert results
    assert any("oauth" in row["text"].lower() for row in results)
