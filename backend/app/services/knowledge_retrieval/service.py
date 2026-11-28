"""Hybrid knowledge retrieval — the single entry point over tiers 1 and 2."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import KnowledgeChunk
from ..knowledge_chunking import search_knowledge_chunks
from ..knowledge_graph import get_claims_for_node, search_graph_nodes
from ..knowledge_graph.query_keywords import extract_query_keywords
from ..knowledge_graph.retrieval import search_graph_edges
from .reranker import rerank_chunks, resolve_reranker_model

MODE_NAIVE = "naive"
MODE_LOCAL = "local"
MODE_MIX = "mix"
_VALID_MODES = {MODE_NAIVE, MODE_LOCAL, MODE_MIX}


async def _provenance_chunks(
    db: AsyncSession, entities: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    refs = []
    for entity in entities:
        for ref in entity.get("source_refs") or []:
            if isinstance(ref, str) and ref.startswith("km:") and ref not in refs:
                refs.append(ref)
    if not refs:
        return []
    rows = (
        (
            await db.execute(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.source_ref.in_(refs[:20]))
                .order_by(KnowledgeChunk.source_ref, KnowledgeChunk.chunk_index)
                .limit(max(1, min(limit, 20)))
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "project_id": row.project_id,
            "source_ref": row.source_ref,
            "source_kind": row.source_kind,
            "chunk_index": row.chunk_index,
            "text": row.text,
            "score": None,
            "provenance": "entity_source",
        }
        for row in rows
    ]


async def _entity_facts(db: AsyncSession, entities: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for entity in entities[:6]:
        for claim in await get_claims_for_node(db, node_id=entity["id"]):
            facts.append(
                {
                    "subject": entity["display_name"],
                    "statement": claim.statement,
                    "type": claim.claim_type,
                    "valid_from": claim.valid_from_label,
                    "valid_until": claim.valid_until_label,
                }
            )
            if len(facts) >= limit:
                return facts
    return facts


async def _naive_chunks(
    db: AsyncSession, *, query: str, project_ids: list[str] | None, chunk_limit: int
) -> list[dict[str, Any]]:
    reranker_model = resolve_reranker_model()
    # With a reranker configured, over-fetch bi-encoder candidates and let the
    # cross-encoder pick the strongest passages for the context budget.
    fetch_limit = min(chunk_limit * 4, 32) if reranker_model else chunk_limit
    chunks = await search_knowledge_chunks(
        db, query=query, project_ids=project_ids, limit=fetch_limit
    )
    if reranker_model:
        chunks = rerank_chunks(query, chunks, model=reranker_model, limit=chunk_limit)
    return chunks


def _add_neighbor_relations(relations: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> None:
    seen = {(r.get("from"), r.get("edge_type"), r.get("to")) for r in relations}
    for node in nodes:
        name = node["display_name"]
        for neighbor in node.get("neighbors", []):
            other_name = (neighbor.get("node") or {}).get("display_name")
            outgoing = neighbor.get("direction") == "out"
            key = (
                name if outgoing else other_name,
                neighbor.get("edge_type"),
                other_name if outgoing else name,
            )
            if key in seen:
                continue
            seen.add(key)
            relations.append(
                {
                    "from": key[0],
                    "edge_type": key[1],
                    "to": key[2],
                    "description": neighbor.get("description"),
                    "trust_level": neighbor.get("trust_level"),
                    "score": None,
                }
            )


async def _local_retrieval(
    db: AsyncSession,
    result: dict[str, Any],
    keywords: Any,
    *,
    project_ids: list[str] | None,
    chunk_limit: int,
    node_limit: int,
    node_types: list[str] | None,
) -> None:
    low_query = keywords.low_text(result["query"]) if keywords else result["query"]
    high_query = keywords.high_text(result["query"]) if keywords else result["query"]

    nodes = await search_graph_nodes(
        db,
        query=low_query,
        project_ids=project_ids,
        node_types=node_types,
        limit=node_limit,
        with_neighbors=True,
        # Entity linking always sees the user's exact identifiers, even when
        # the keyword rewrite dropped them (e.g. file names like foo.py).
        alias_query=result["query"],
    )
    result["entities"] = [{k: v for k, v in node.items() if k != "neighbors"} for node in nodes]

    # Relations: high-level edge search first, then neighbor edges of the
    # retrieved entities (deduplicated).
    relations: list[dict[str, Any]] = await search_graph_edges(
        db, query=high_query, project_ids=project_ids, limit=node_limit
    )
    _add_neighbor_relations(relations, nodes)
    result["relations"] = relations

    # Evidence: pull the retrieved entities' own source chunks + their claims.
    provenance = await _provenance_chunks(db, result["entities"], limit=chunk_limit)
    known_chunk_ids = {chunk["id"] for chunk in result["chunks"]}
    result["chunks"].extend(chunk for chunk in provenance if chunk["id"] not in known_chunk_ids)
    result["facts"] = await _entity_facts(db, result["entities"])


async def retrieve_knowledge(
    db: AsyncSession,
    *,
    query: str,
    project_ids: list[str] | None = None,
    mode: str = MODE_MIX,
    chunk_limit: int = 8,
    node_limit: int = 8,
    node_types: list[str] | None = None,
) -> dict[str, Any]:
    """Retrieve a unified result: chunks (recall), entities (low-level),
    relations (high-level), provenance chunks, and versioned facts."""
    resolved_mode = mode if mode in _VALID_MODES else MODE_MIX
    result: dict[str, Any] = {
        "query": str(query or "").strip(),
        "mode": resolved_mode,
        "keywords": {"low_level": [], "high_level": [], "source": "none"},
        "chunks": [],
        "entities": [],
        "relations": [],
        "facts": [],
    }
    if not result["query"]:
        return result

    keywords = None
    if resolved_mode in (MODE_LOCAL, MODE_MIX):
        keywords = await extract_query_keywords(db, query=result["query"], project_ids=project_ids)
        result["keywords"] = {
            "low_level": keywords.low_level,
            "high_level": keywords.high_level,
            "source": keywords.source,
        }

    if resolved_mode in (MODE_NAIVE, MODE_MIX):
        result["chunks"] = await _naive_chunks(
            db, query=result["query"], project_ids=project_ids, chunk_limit=chunk_limit
        )

    if resolved_mode in (MODE_LOCAL, MODE_MIX):
        await _local_retrieval(
            db,
            result,
            keywords,
            project_ids=project_ids,
            chunk_limit=chunk_limit,
            node_limit=node_limit,
            node_types=node_types,
        )
    return result


def build_context_block(result: dict[str, Any], *, max_chars: int = 6000) -> str:
    """Assemble a compact, model-facing context block from a retrieval result."""
    sections: list[str] = []

    entities = result.get("entities") or []
    if entities:
        lines = [f"- {e['display_name']} ({e['node_type']}): {e.get('description') or ''}".rstrip() for e in entities]
        sections.append("Entities:\n" + "\n".join(lines))

    facts = result.get("facts") or []
    if facts:
        lines = []
        for fact in facts:
            validity = ""
            if fact.get("valid_from") or fact.get("valid_until"):
                validity = f" [valid {fact.get('valid_from') or '…'} → {fact.get('valid_until') or '…'}]"
            lines.append(f"- {fact['subject']}: {fact['statement']}{validity}")
        sections.append("Facts:\n" + "\n".join(lines))

    relations = result.get("relations") or []
    if relations:
        lines = [
            f"- {r.get('from')} —{r.get('edge_type')}→ {r.get('to')}"
            + (f": {r['description']}" if r.get("description") else "")
            for r in relations
            if r.get("from") and r.get("to")
        ]
        if lines:
            sections.append("Relations:\n" + "\n".join(lines))

    chunks = result.get("chunks") or []
    if chunks:
        lines = [f"- [{c['source_ref']}] {c['text']}" for c in chunks]
        sections.append("Passages:\n" + "\n".join(lines))

    block = "\n\n".join(sections).strip()
    if len(block) > max_chars:
        block = block[:max_chars].rstrip() + "\n…[truncated]"
    return block
