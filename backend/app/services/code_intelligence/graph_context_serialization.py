"""Serialized views of the candidates a budgeted Code Graph context selected."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from app.services.code_intelligence.graph_context_scoring import _edge_semantics
from app.services.code_intelligence.graph_query_serializers import serialize_node

if TYPE_CHECKING:
    from app.services.code_intelligence.graph_context_selection import ContextCandidate


def _retrieval_provenance(
    selected: list[ContextCandidate], *, selected_edges: list[dict[str, Any]], query: str | None
) -> dict[str, Any]:
    return {
        "query": query or "",
        "matched_symbols": [_matched_symbol(item) for item in selected if item.node.node_type != "file"],
        "graph_edges": selected_edges,
        "text_matches": _text_matches(selected, query=query),
        "staleness_notes": [
            {
                "path": item.node.path,
                "node_id": item.node.id,
                "reason": "node_marked_stale",
            }
            for item in selected
            if item.node.is_stale
        ],
        "selection_signals": _selection_signal_counts(selected),
    }


def _context_files(selected_nodes: list[ContextCandidate]) -> list[dict[str, Any]]:
    by_path: dict[str, list[ContextCandidate]] = defaultdict(list)
    for item in selected_nodes:
        path = str(item.node.path or "").strip()
        if path:
            by_path[path].append(item)
    return [
        {
            "path": path,
            "node_count": len(nodes),
            "nodes": [
                {
                    "id": item.node.id,
                    "name": item.node.name,
                    "node_type": item.node.node_type,
                    "line_start": item.node.line_start,
                    "selection_signals": item.signals,
                }
                for item in nodes
            ],
            "source_chunks": _dedupe_source_chunks(nodes),
        }
        for path, nodes in sorted(by_path.items())
    ]


def _dedupe_source_chunks(nodes: list[ContextCandidate]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for item in sorted(nodes, key=lambda candidate: (candidate.node.line_start or 0, candidate.node.name or "")):
        chunk = item.source_chunk
        if not chunk:
            continue
        key = (str(chunk.get("path") or ""), int(chunk.get("line_start") or 0), int(chunk.get("line_end") or 0))
        if key in seen:
            continue
        seen.add(key)
        chunks.append(chunk)
    return chunks


def _relationship_map(selected_edges: list[dict[str, Any]], *, selected_ids: set[str]) -> list[dict[str, Any]]:
    rows = []
    for item in selected_edges:
        edge = item["edge"]
        if edge["source_node_id"] not in selected_ids or edge["target_node_id"] not in selected_ids:
            continue
        rows.append(
            {
                "source_node_id": edge["source_node_id"],
                "target_node_id": edge["target_node_id"],
                "relation": edge["relation"],
                "confidence": edge["confidence"],
                "semantics": _edge_semantics(edge["relation"]),
            }
        )
    return rows


def _serialize_candidate(item: ContextCandidate, *, start_node_id: str) -> dict[str, Any]:
    return {
        "node": serialize_node(item.node),
        "depth": item.depth,
        "selection_reason": "start_node" if item.node.id == start_node_id else "ranked_graph_neighbor",
        "selection_signals": item.signals,
        "retrieval_score": list(item.score),
        "context_text": item.context_text,
        "source_chunk": item.source_chunk,
        "file_metadata": item.file_metadata,
        "estimated_chars": item.estimated_chars,
    }


def _serialize_omitted_candidate(item: ContextCandidate) -> dict[str, Any]:
    return {
        "node": serialize_node(item.node),
        "depth": item.depth,
        "selection_signals": item.signals,
        "retrieval_score": list(item.score),
        "estimated_chars": item.estimated_chars,
        "omitted_reason": "budget_capped",
    }


def _matched_symbol(item: ContextCandidate) -> dict[str, Any]:
    return {
        "node_id": item.node.id,
        "name": item.node.name,
        "node_type": item.node.node_type,
        "path": item.node.path,
        "line_start": item.node.line_start,
        "confidence": item.node.confidence,
        "selection_signals": item.signals,
    }


def _text_matches(selected: list[ContextCandidate], *, query: str | None) -> list[dict[str, Any]]:
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches = []
    for item in selected:
        chunk = item.source_chunk or {}
        content = str(chunk.get("content") or "")
        if needle not in content.lower():
            continue
        matches.append(
            {
                "path": chunk.get("path") or item.node.path,
                "line_start": chunk.get("line_start") or item.node.line_start,
                "line_end": chunk.get("line_end") or item.node.line_end,
                "match": "source_chunk",
                "node_id": item.node.id,
            }
        )
    return matches


def _selection_signal_counts(selected: list[ContextCandidate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in selected:
        for signal in item.signals:
            counts[signal] = counts.get(signal, 0) + 1
    return counts
