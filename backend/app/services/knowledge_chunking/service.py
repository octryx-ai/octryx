"""Chunk indexing and retrieval — the naive vector-RAG layer (tier 1)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import KnowledgeChunk
from ...time_utils import utc_now
from ..knowledge_embedding import (
    EmbeddingConfigurationError,
    resolve_knowledge_embedding_runtime,
)
from ..knowledge_embedding.scoring import compute_semantic_similarity
from ..knowledge_graph.retrieval import keyword_signal
from .chunker import chunk_document

logger = logging.getLogger(__name__)


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _upsert_chunk_rows(
    db: AsyncSession,
    chunks: list[Any],
    existing: dict[int, KnowledgeChunk],
    *,
    project_id: str,
    source_ref: str,
    source_kind: str,
    tags: list[str] | None,
) -> tuple[set[int], list[KnowledgeChunk], dict[str, int]]:
    seen: set[int] = set()
    to_embed: list[KnowledgeChunk] = []
    counts = {"created": 0, "updated": 0, "unchanged": 0}

    for chunk in chunks:
        seen.add(chunk.index)
        digest = _content_hash(chunk.text)
        row = existing.get(chunk.index)
        if row is None:
            row = KnowledgeChunk(
                id=str(uuid.uuid4()),
                project_id=project_id,
                source_ref=source_ref,
                source_kind=source_kind,
                chunk_index=chunk.index,
                text=chunk.text,
                token_count=chunk.token_count,
                content_hash=digest,
                tags=list(tags or []),
            )
            db.add(row)
            counts["created"] += 1
            to_embed.append(row)
        elif row.content_hash != digest:
            row.text = chunk.text
            row.token_count = chunk.token_count
            row.content_hash = digest
            row.source_kind = source_kind
            row.tags = list(tags or row.tags or [])
            row.embedding = None
            row.embedding_updated_at = None
            counts["updated"] += 1
            to_embed.append(row)
        else:
            counts["unchanged"] += 1
    return seen, to_embed, counts


async def _embed_chunk_rows(db: AsyncSession, to_embed: list[KnowledgeChunk]) -> tuple[int, str | None]:
    embedded = 0
    embed_error: str | None = None
    if to_embed:
        try:
            provider = await resolve_knowledge_embedding_runtime(db)
            vectors = provider.embed_texts([row.text for row in to_embed])
            now = utc_now()
            for row, vector in zip(to_embed, vectors, strict=False):
                row.embedding = vector
                row.embedding_provider = provider.provider_id
                row.embedding_model = provider.model
                row.embedding_version = provider.version
                row.embedding_updated_at = now
                embedded += 1
            await db.flush()
        except EmbeddingConfigurationError as exc:
            # Chunks are stored without vectors; a reindex backfills them once a
            # provider is configured. No silent hash substitution.
            embed_error = str(exc)
            logger.warning(
                "Chunk embedding unavailable; stored %d chunk(s) without vectors: %s",
                len(to_embed),
                exc,
            )
    return embedded, embed_error


async def index_source_chunks(
    db: AsyncSession,
    *,
    project_id: str,
    source_ref: str,
    text: str,
    source_kind: str = "document",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Incrementally (re)index a source's text into chunks."""
    chunks = chunk_document(text)
    existing_rows = (
        (
            await db.execute(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.project_id == project_id,
                    KnowledgeChunk.source_ref == source_ref,
                )
            )
        )
        .scalars()
        .all()
    )
    existing = {row.chunk_index: row for row in existing_rows}

    seen, to_embed, counts = _upsert_chunk_rows(
        db, chunks, existing, project_id=project_id, source_ref=source_ref, source_kind=source_kind, tags=tags
    )

    deleted = 0
    for index, row in existing.items():
        if index not in seen:
            await db.delete(row)
            deleted += 1

    await db.flush()

    embedded, embed_error = await _embed_chunk_rows(db, to_embed)

    return {
        "source_ref": source_ref,
        "total_chunks": len(chunks),
        "created": counts["created"],
        "updated": counts["updated"],
        "unchanged": counts["unchanged"],
        "deleted": deleted,
        "embedded": embedded,
        "embed_error": embed_error,
    }


async def search_knowledge_chunks(
    db: AsyncSession,
    *,
    query: str,
    project_ids: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    query_text = str(query or "").strip()
    if not query_text:
        return []

    query_embedding: list[float] = []
    try:
        query_embedding = (await resolve_knowledge_embedding_runtime(db)).embed_text(query_text, is_query=True)
    except EmbeddingConfigurationError as exc:
        logger.warning("Chunk query embedding unavailable; keyword-only recall: %s", exc)

    stmt = select(KnowledgeChunk)
    normalized_projects = [str(p).strip() for p in (project_ids or []) if str(p or "").strip()]
    if normalized_projects:
        # Project-scoped chunks plus instance-global ones (project_id NULL) —
        # same visibility rule as graph-node search.
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                KnowledgeChunk.project_id.in_(normalized_projects),
                KnowledgeChunk.project_id.is_(None),
            )
        )
    rows = (await db.execute(stmt)).scalars().all()

    scored: list[tuple[KnowledgeChunk, float]] = []
    for row in rows:
        semantic = (
            compute_semantic_similarity(query_embedding, row.embedding if isinstance(row.embedding, list) else None)
            if query_embedding
            else 0.0
        )
        keyword = keyword_signal(query_text, row.text or "")
        score = (0.7 * semantic + 0.3 * keyword) if query_embedding else keyword
        if score > 0:
            scored.append((row, score))

    scored.sort(key=lambda item: (-item[1], item[0].source_ref or "", item[0].chunk_index))
    safe_limit = max(1, min(int(limit or 10), 100))
    return [
        {
            "id": row.id,
            "project_id": row.project_id,
            "source_ref": row.source_ref,
            "source_kind": row.source_kind,
            "chunk_index": row.chunk_index,
            "text": row.text,
            "score": round(score, 6),
        }
        for row, score in scored[:safe_limit]
    ]


async def reindex_knowledge_chunks(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    provider = await resolve_knowledge_embedding_runtime(db)
    stmt = select(KnowledgeChunk).where(
        or_(
            KnowledgeChunk.embedding_updated_at.is_(None),
            KnowledgeChunk.embedding_provider.is_(None),
            KnowledgeChunk.embedding_provider != provider.provider_id,
            KnowledgeChunk.embedding_model.is_(None),
            KnowledgeChunk.embedding_model != provider.model,
            KnowledgeChunk.embedding_version.is_(None),
            KnowledgeChunk.embedding_version != provider.version,
        )
    )
    if project_id:
        stmt = stmt.where(KnowledgeChunk.project_id == project_id)
    rows = (await db.execute(stmt.limit(max(1, min(int(limit or 200), 1000))))).scalars().all()
    if not rows:
        return {"reindexed": 0, "provider": provider.provider_id, "model": provider.model}

    vectors = provider.embed_texts([row.text for row in rows])
    now = utc_now()
    for row, vector in zip(rows, vectors, strict=False):
        row.embedding = vector
        row.embedding_provider = provider.provider_id
        row.embedding_model = provider.model
        row.embedding_version = provider.version
        row.embedding_updated_at = now
    await db.flush()
    return {"reindexed": len(rows), "provider": provider.provider_id, "model": provider.model}
