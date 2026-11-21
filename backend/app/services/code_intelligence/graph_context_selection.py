"""Selection and budgeting helpers for native Code Graph context retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphEdge, CodeGraphFile, CodeGraphNode
from app.services.code_intelligence.graph_context_scoring import (
    _candidate_score,
    _context_budget,
    _edge_context_text,
    _edge_sort_key,
    _node_context_text,
    _route_node_ids,
    _selection_signals,
)
from app.services.code_intelligence.graph_context_serialization import (
    _context_files,
    _relationship_map,
    _retrieval_provenance,
    _serialize_candidate,
    _serialize_omitted_candidate,
)
from app.services.code_intelligence.graph_query_engine import source_chunk_for_node
from app.services.code_intelligence.graph_query_serializers import serialize_edge
from app.services.code_intelligence.graph_query_support import GraphContext


@dataclass(frozen=True)
class ContextCandidate:
    node: CodeGraphNode
    depth: int
    source_chunk: dict[str, Any] | None
    file_metadata: dict[str, Any]
    score: tuple[int, int, int, str, int, str]
    signals: list[str]
    context_text: str
    estimated_chars: int


async def build_budgeted_context(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    start: CodeGraphNode,
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
    depth_by_node: dict[str, int],
    query: str | None,
    requested_budget_chars: int,
) -> dict[str, Any]:
    file_metadata = await _file_metadata_by_id(db, run_id=ctx.run.id)
    source_chunks = await _source_chunks_by_node_id(db, ctx=ctx, nodes=nodes)
    candidates = [
        _candidate_for_node(
            node,
            start_node_id=start.id,
            depth=depth_by_node.get(node.id, 0),
            query=query,
            source_chunk=source_chunks.get(node.id),
            file_metadata=file_metadata.get(node.source_file_id or "", {}),
            route_node_ids=_route_node_ids(edges),
        )
        for node in nodes
    ]
    char_budget, budget_policy = _context_budget(
        requested_budget_chars,
        file_count=int(ctx.run.file_count or 0),
        query=query,
    )
    selected, omitted = _select_candidates(candidates, budget_chars=char_budget)
    selected_ids = {item.node.id for item in selected}
    selected_edges, edge_chars, omitted_edges = _select_edges(
        edges,
        selected_node_ids=selected_ids,
        remaining_chars=max(0, char_budget - sum(item.estimated_chars for item in selected)),
    )
    used_chars = sum(item.estimated_chars for item in selected) + edge_chars
    return {
        "context_nodes": [_serialize_candidate(item, start_node_id=start.id) for item in selected],
        "context_edges": selected_edges,
        "context_files": _context_files(selected),
        "relationship_map": _relationship_map(selected_edges, selected_ids=selected_ids),
        "not_shown_candidates": [_serialize_omitted_candidate(item) for item in omitted[:10]],
        "budget": {
            "requested_chars": char_budget,
            "requested_input_chars": int(requested_budget_chars or 0),
            "used_chars": used_chars,
            "remaining_chars": max(0, char_budget - used_chars),
            "omitted_nodes": len(omitted),
            "omitted_edges": omitted_edges,
            "policy": budget_policy,
        },
        "truncated": bool(omitted or omitted_edges),
        "retrieval_provenance": _retrieval_provenance(selected, selected_edges=selected_edges, query=query),
    }


async def _file_metadata_by_id(db: AsyncSession, *, run_id: str) -> dict[str, dict[str, Any]]:
    rows = (
        await db.execute(
            select(CodeGraphFile).where(
                CodeGraphFile.run_id == run_id,
                CodeGraphFile.is_current.is_(True),
            )
        )
    ).scalars().all()
    return {row.id: row.file_metadata or {} for row in rows}


async def _source_chunks_by_node_id(
    db: AsyncSession, *, ctx: GraphContext, nodes: list[CodeGraphNode]
) -> dict[str, dict[str, Any] | None]:
    chunks: dict[str, dict[str, Any] | None] = {}
    for node in nodes:
        chunks[node.id] = await source_chunk_for_node(db, ctx=ctx, node=node)
    return chunks


def _candidate_for_node(
    node: CodeGraphNode,
    *,
    start_node_id: str,
    depth: int,
    query: str | None,
    source_chunk: dict[str, Any] | None,
    file_metadata: dict[str, Any],
    route_node_ids: set[str],
) -> ContextCandidate:
    signals = _selection_signals(
        node,
        start_node_id=start_node_id,
        depth=depth,
        query=query,
        file_metadata=file_metadata,
        route_node_ids=route_node_ids,
    )
    score = _candidate_score(
        node,
        start_node_id=start_node_id,
        depth=depth,
        query=query,
        file_metadata=file_metadata,
        route_node_ids=route_node_ids,
    )
    context_text = _node_context_text(node, depth=depth, score=score, signals=signals)
    estimated_chars = len(context_text) + len(str((source_chunk or {}).get("content") or ""))
    return ContextCandidate(
        node=node,
        depth=depth,
        source_chunk=source_chunk,
        file_metadata=file_metadata,
        score=score,
        signals=signals,
        context_text=context_text,
        estimated_chars=max(1, estimated_chars),
    )


def _select_candidates(
    candidates: list[ContextCandidate], *, budget_chars: int
) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
    selected: list[ContextCandidate] = []
    omitted: list[ContextCandidate] = []
    used = 0
    for item in sorted(candidates, key=lambda candidate: candidate.score):
        # Every serialized candidate carries its chunk; selection must count each copy.
        cost = item.estimated_chars
        if used + cost > budget_chars:
            omitted.append(item)
            continue
        selected.append(item)
        used += cost
    return selected, omitted


def _select_edges(
    edges: list[CodeGraphEdge],
    *,
    selected_node_ids: set[str],
    remaining_chars: int,
) -> tuple[list[dict[str, Any]], int, int]:
    selected: list[dict[str, Any]] = []
    used = 0
    omitted = 0
    for edge in sorted(edges, key=_edge_sort_key):
        if edge.source_node_id not in selected_node_ids or edge.target_node_id not in selected_node_ids:
            omitted += 1
            continue
        text = _edge_context_text(edge)
        cost = len(text)
        if used + cost > remaining_chars:
            omitted += 1
            continue
        selected.append({"edge": serialize_edge(edge), "context_text": text, "estimated_chars": cost})
        used += cost
    return selected, used, omitted
