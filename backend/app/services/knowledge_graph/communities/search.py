"""Community retrieval and the GraphRAG-style global answer."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog.out_of_turn import prompt_set_for, single_workspace

from ....models import KnowledgeCommunity
from ...knowledge_embedding import EmbeddingConfigurationError, resolve_knowledge_embedding_runtime
from ...knowledge_embedding.scoring import compute_semantic_similarity
from .reports import GenerateFn

# The package name keeps the log records under the communities logger.
logger = logging.getLogger(__package__)


async def global_search(
    db: AsyncSession,
    *,
    query: str,
    generate: GenerateFn,
    project_ids: list[str] | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    """GraphRAG-style global answer from the top-K community reports, in one governed LLM call. Without a runtime it
    raises; the caller decides."""
    candidates = await search_communities(db, query=query, project_ids=project_ids, limit=top_k)
    if not candidates:
        return {"answer": "", "communities_used": [], "candidates": 0}
    report_lines = "\n\n".join(
        f"[{index + 1}] {community['title']} (size {community['size']}):\n{community['summary']}"
        for index, community in enumerate(candidates)
    )
    prompt = (await prompt_set_for(db, workspace_id=single_workspace(project_ids))).render(
        "knowledge.graph.global_answer", query=query.strip()[:500], report_lines=report_lines[:8000]
    )
    answer = str(await generate(prompt) or "").strip()
    return {
        "answer": answer,
        "communities_used": [{"title": c["title"], "id": c["id"]} for c in candidates],
        "candidates": len(candidates),
    }


def _score_rows(rows: list[Any], query_text: str, query_embedding: list[float]) -> list[tuple[Any, float]]:
    from ..retrieval import keyword_signal

    scored: list[tuple[KnowledgeCommunity, float]] = []
    for row in rows:
        keyword = keyword_signal(query_text, f"{row.title} {row.summary}")
        semantic = (
            compute_semantic_similarity(query_embedding, row.embedding if isinstance(row.embedding, list) else None)
            if query_embedding
            else 0.0
        )
        score = (0.6 * semantic + 0.4 * keyword) if query_embedding else keyword
        if score > 0:
            scored.append((row, score))
    scored.sort(key=lambda item: (-item[1], item[0].title or ""))
    return scored


async def search_communities(
    db: AsyncSession,
    *,
    query: str,
    project_ids: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    query_text = str(query or "").strip()
    if not query_text:
        return []
    query_embedding: list[float] = []
    try:
        query_embedding = (await resolve_knowledge_embedding_runtime(db)).embed_text(query_text, is_query=True)
    except EmbeddingConfigurationError as exc:
        logger.warning("Community query embedding unavailable; keyword-only: %s", exc)

    stmt = select(KnowledgeCommunity).where(KnowledgeCommunity.status == "active")
    normalized = [str(p).strip() for p in (project_ids or []) if str(p or "").strip()]
    if normalized:
        stmt = stmt.where(
            or_(KnowledgeCommunity.project_id.in_(normalized), KnowledgeCommunity.project_id.is_(None))
        )
    rows = (await db.execute(stmt)).scalars().all()

    scored = _score_rows(rows, query_text, query_embedding)
    return [
        {
            "id": row.id,
            "title": row.title,
            "summary": row.summary,
            "size": int(row.size or 0),
            "summary_source": row.summary_source,
            "score": round(score, 6),
        }
        for row, score in scored[: max(1, min(int(limit or 5), 50))]
    ]
