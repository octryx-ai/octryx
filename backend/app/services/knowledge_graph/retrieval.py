"""Graph retrieval: rank entity nodes and relation edges by semantic and keyword signal. Instance-global nodes are
always in scope."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import KnowledgeGraphAlias, KnowledgeGraphEdge, KnowledgeGraphNode
from ..knowledge_embedding import EmbeddingConfigurationError, resolve_knowledge_embedding_runtime
from ..knowledge_embedding.scoring import compute_semantic_similarity
from .store import get_neighbors

logger = logging.getLogger(__name__)

# ``compute_semantic_similarity`` maps cosine [-1, 1] onto [0, 1], so unrelated vectors sit near 0.5.
# A node counts as a semantic *match* only from cosine 0.6 upward; below that it is ranking noise.
SEMANTIC_MATCH_THRESHOLD = 0.8


_QUERY_STOPWORDS = {
    "and", "any", "are", "can", "current", "did", "does", "for", "from", "have",
    "how", "its", "last", "made", "the", "their", "this", "updated",
    "version", "was", "what", "when", "where", "which", "who", "why",
    "with", "you",
}


def _terms(text: str) -> list[str]:
    return [
        term
        for term in " ".join(str(text or "").lower().split()).split()
        if len(term) >= 3 and term.strip("'\"?.,:;()") not in _QUERY_STOPWORDS
    ]


def keyword_signal(query: str, haystack: str, *, name: str = "") -> float:
    needle = " ".join(str(query or "").lower().split())
    haystack = str(haystack or "").lower()
    if not needle or not haystack:
        return 0.0
    normalized_name = " ".join(str(name or "").lower().split())
    if normalized_name and len(normalized_name) >= 4:
        # Word-boundary match: 'gitops' must not fire inside 'demo-shop-gitops'.
        import re as _re

        if _re.search(rf"(?<![\w-]){_re.escape(normalized_name)}(?![\w-])", needle):
            return 1.0
    if needle in haystack:
        return 1.0
    terms = _terms(needle)
    if not terms:
        return 0.0
    matched = sum(1 for term in terms if term.strip("'\"?.,:;()") in haystack)
    if matched == len(terms):
        return 0.7
    return 0.5 * (matched / len(terms))


async def _query_embedding(db: AsyncSession, query_text: str, unavailable_message: str) -> list[float]:
    query_embedding: list[float] = []
    try:
        query_embedding = (await resolve_knowledge_embedding_runtime(db)).embed_text(query_text, is_query=True)
    except EmbeddingConfigurationError as exc:
        logger.warning(unavailable_message, exc)
    return query_embedding


def _project_scoped(stmt, model, project_ids: list[str] | None):
    normalized_projects = [str(p).strip() for p in (project_ids or []) if str(p or "").strip()]
    if normalized_projects:
        # Project-scoped rows for the given projects, plus instance-global rows.
        stmt = stmt.where(
            or_(
                model.project_id.in_(normalized_projects),
                model.project_id.is_(None),
            )
        )
    return stmt


def _blended_score(query_text: str, haystack: str, query_embedding: list[float], embedding, *, name: str = ""):
    keyword = keyword_signal(query_text, haystack, name=name)
    semantic = (
        compute_semantic_similarity(query_embedding, embedding if isinstance(embedding, list) else None)
        if query_embedding
        else 0.0
    )
    score = (0.6 * semantic + 0.4 * keyword) if query_embedding else keyword
    return score, keyword, semantic


def _score_nodes(
    rows, query_text: str, query_embedding: list[float], alias_hits: set[str], matches_only: bool
) -> list[tuple[KnowledgeGraphNode, float]]:
    scored: list[tuple[KnowledgeGraphNode, float]] = []
    for row in rows:
        haystack = f"{row.display_name} {row.description}"
        score, keyword, semantic = _blended_score(
            query_text, haystack, query_embedding, row.embedding, name=row.display_name
        )
        if row.id in alias_hits:
            score += 0.5  # exact alias match outranks fuzzy name overlaps
        if matches_only and not (keyword > 0 or row.id in alias_hits or semantic >= SEMANTIC_MATCH_THRESHOLD):
            continue
        if score > 0:
            scored.append((row, score))
    scored.sort(key=lambda item: (-item[1], item[0].display_name or ""))
    return scored


async def search_graph_nodes(
    db: AsyncSession,
    *,
    query: str,
    project_ids: list[str] | None = None,
    node_types: list[str] | None = None,
    limit: int = 10,
    with_neighbors: bool = False,
    alias_query: str | None = None,
    matches_only: bool = False,
) -> list[dict[str, Any]]:
    """Rank entity nodes for ``query``; ``alias_query`` carries the original question for entity linking."""
    query_text = str(query or "").strip()
    if not query_text:
        return []

    query_embedding = await _query_embedding(
        db, query_text, "Graph query embedding unavailable; keyword-only recall: %s"
    )

    stmt = _project_scoped(
        select(KnowledgeGraphNode).where(KnowledgeGraphNode.status == "active"), KnowledgeGraphNode, project_ids
    )
    if node_types:
        stmt = stmt.where(KnowledgeGraphNode.node_type.in_([str(t).strip().lower() for t in node_types]))

    rows = (await db.execute(stmt)).scalars().all()

    # Deterministic entity linking: query n-grams that EXACTLY match an alias
    # (usernames, repo slugs, emails, titles) pin their nodes to the top —
    # that is what the alias table exists for.
    alias_source = str(alias_query or "").strip() or query_text
    alias_hits = await _alias_matches(db, alias_source)
    if alias_source != query_text:
        alias_hits |= await _alias_matches(db, query_text)

    scored = _score_nodes(rows, query_text, query_embedding, alias_hits, matches_only)
    safe_limit = max(1, min(int(limit or 10), 100))
    results: list[dict[str, Any]] = []
    for row, score in scored[:safe_limit]:
        entry: dict[str, Any] = {
            "id": row.id,
            "node_type": row.node_type,
            "display_name": row.display_name,
            "description": row.description,
            "trust_level": row.trust_level,
            "source_refs": list(row.source_refs or []),
            "score": round(score, 6),
        }
        if with_neighbors:
            entry["neighbors"] = await get_neighbors(db, node_id=row.id, limit=10)
        results.append(entry)
    return results


async def _alias_matches(db: AsyncSession, query: str) -> set[str]:
    words = " ".join(str(query or "").lower().split()).strip("?.!,:;'\"").split()
    ngrams: set[str] = set()
    for size in (1, 2, 3):
        for start in range(0, max(0, len(words) - size + 1)):
            gram = " ".join(words[start : start + size]).strip("?.!,:;'\"")
            if len(gram) >= 3:
                ngrams.add(gram)
    if not ngrams:
        return set()
    rows = (
        await db.execute(
            select(KnowledgeGraphAlias.node_id).where(KnowledgeGraphAlias.normalized_alias.in_(ngrams))
        )
    ).all()
    return {row[0] for row in rows}


async def _edge_results(db: AsyncSession, scored: list[tuple[KnowledgeGraphEdge, float]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    node_cache: dict[str, KnowledgeGraphNode | None] = {}

    async def _node(node_id: str) -> KnowledgeGraphNode | None:
        if node_id not in node_cache:
            node_cache[node_id] = await db.get(KnowledgeGraphNode, node_id)
        return node_cache[node_id]

    for edge, score in scored:
        source = await _node(edge.source_node_id)
        target = await _node(edge.target_node_id)
        results.append(
            {
                "edge_type": edge.edge_type,
                "description": edge.description,
                "from": source.display_name if source else None,
                "to": target.display_name if target else None,
                "trust_level": edge.trust_level,
                "source_refs": list(edge.source_refs or []),
                "score": round(score, 6),
            }
        )
    return results


async def search_graph_edges(
    db: AsyncSession,
    *,
    query: str,
    project_ids: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """High-level retrieval: rank RELATIONS by their description/keyword
    embeddings (LightRAG's thematic level) and return them with endpoint names."""
    query_text = str(query or "").strip()
    if not query_text:
        return []

    query_embedding = await _query_embedding(
        db, query_text, "Edge query embedding unavailable; keyword-only recall: %s"
    )

    stmt = _project_scoped(
        select(KnowledgeGraphEdge).where(KnowledgeGraphEdge.status == "active"), KnowledgeGraphEdge, project_ids
    )
    edges = (await db.execute(stmt)).scalars().all()

    scored: list[tuple[KnowledgeGraphEdge, float]] = []
    for edge in edges:
        haystack = f"{edge.edge_type} {edge.description or ''} {' '.join(edge.keywords or [])}"
        score, _, _ = _blended_score(query_text, haystack, query_embedding, edge.embedding)
        if score > 0:
            scored.append((edge, score))

    scored.sort(key=lambda item: (-item[1] * float(item[0].weight or 1.0), item[0].id))
    safe_limit = max(1, min(int(limit or 10), 100))
    return await _edge_results(db, scored[:safe_limit])
