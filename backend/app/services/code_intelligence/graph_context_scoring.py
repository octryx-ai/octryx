"""Ranking signals, scores and budget policy for native Code Graph context selection."""

from __future__ import annotations

from typing import Any

from app.models import CodeGraphEdge, CodeGraphNode

MAX_CONTEXT_BUDGET_CHARS = 20000
MIN_CONTEXT_BUDGET_CHARS = 500


def _selection_signals(
    node: CodeGraphNode,
    *,
    start_node_id: str,
    depth: int,
    query: str | None,
    file_metadata: dict[str, Any],
    route_node_ids: set[str],
) -> list[str]:
    signals = ["start_node" if node.id == start_node_id else f"graph_depth_{depth}"]
    if node.id in route_node_ids or node.node_type == "route":
        signals.append("route_relevance")
    if _query_matches(node, query):
        signals.append("symbol_match")
    if file_metadata.get("is_generated"):
        signals.append("generated_downranked")
    if file_metadata.get("is_vendor"):
        signals.append("vendor_downranked")
    if file_metadata.get("is_test") or node.node_type == "test":
        signals.append("test_downranked")
    if node.is_stale:
        signals.append("stale")
    return signals


def _candidate_score(
    node: CodeGraphNode,
    *,
    start_node_id: str,
    depth: int,
    query: str | None,
    file_metadata: dict[str, Any],
    route_node_ids: set[str],
) -> tuple[int, int, int, str, int, str]:
    start_rank = 0 if node.id == start_node_id else 1
    route_rank = 0 if node.id in route_node_ids or node.node_type == "route" else 1
    query_rank = 0 if _query_matches(node, query) else 1
    penalty = 0
    if file_metadata.get("is_generated"):
        penalty += 12
    if file_metadata.get("is_vendor"):
        penalty += 10
    if file_metadata.get("is_test") or node.node_type == "test":
        penalty += 4
    return (
        start_rank,
        max(0, int(depth or 0)),
        route_rank + query_rank + penalty,
        node.path or "",
        node.line_start or 0,
        node.name or "",
    )


def _query_matches(node: CodeGraphNode, query: str | None) -> bool:
    needle = str(query or "").strip().lower()
    if not needle:
        return False
    haystack = " ".join(
        [
            str(node.name or ""),
            str(node.path or ""),
            str(node.external_id or ""),
            str(node.signature or ""),
            str((node.node_metadata or {}).get("qualified_name") or ""),
        ]
    ).lower()
    return needle in haystack


def _route_node_ids(edges: list[CodeGraphEdge]) -> set[str]:
    ids: set[str] = set()
    for edge in edges:
        if edge.relation == "routes_to":
            ids.add(edge.source_node_id)
            ids.add(edge.target_node_id)
    return ids


def _node_context_text(
    node: CodeGraphNode,
    *,
    depth: int,
    score: tuple[int, int, int, str, int, str],
    signals: list[str],
) -> str:
    location = f"{node.path or '<unknown>'}:{node.line_start or '?'}"
    if node.line_end and node.line_end != node.line_start:
        location = f"{location}-{node.line_end}"
    parts = [
        f"depth={depth}",
        f"type={node.node_type}",
        f"name={node.name}",
        f"location={location}",
        f"confidence={node.confidence}",
        f"stale={bool(node.is_stale)}",
        f"score={list(score)}",
        f"signals={','.join(signals)}",
    ]
    if node.signature:
        parts.append(f"signature={node.signature}")
    return " | ".join(parts)


def _edge_context_text(edge: CodeGraphEdge) -> str:
    return (
        f"relation={edge.relation} | source={edge.source_node_id} | target={edge.target_node_id} | "
        f"confidence={edge.confidence}"
    )


def _edge_sort_key(edge: CodeGraphEdge) -> tuple[int, str, str, str]:
    priority = {"routes_to": 0, "calls": 1, "tested_by": 2, "references": 3, "imports": 4}.get(edge.relation, 9)
    return (priority, edge.relation, edge.source_node_id, edge.target_node_id)


def _edge_semantics(relation: str) -> str:
    if relation == "routes_to":
        return "route_binding"
    if relation == "calls":
        return "direct_static_call"
    if relation == "tested_by":
        return "test_coverage"
    if relation == "imports":
        return "module_dependency"
    return "graph_reference"


def _context_budget(value: int, *, file_count: int, query: str | None) -> tuple[int, dict[str, Any]]:
    requested = int(value or 0)
    adaptive_default = 4000 if file_count <= 20 else 8000 if file_count <= 200 else 12000
    query_text = str(query or "").lower()
    if any(token in query_text for token in ("flow", "endpoint", "route", "migration", "refactor", "impact")):
        adaptive_default += 2000
    chosen = requested if requested > 0 else adaptive_default
    bounded = max(MIN_CONTEXT_BUDGET_CHARS, min(chosen, MAX_CONTEXT_BUDGET_CHARS))
    return bounded, {
        "mode": "requested" if requested > 0 else "adaptive",
        "adaptive_default_chars": max(MIN_CONTEXT_BUDGET_CHARS, min(adaptive_default, MAX_CONTEXT_BUDGET_CHARS)),
        "min_chars": MIN_CONTEXT_BUDGET_CHARS,
        "max_chars": MAX_CONTEXT_BUDGET_CHARS,
        "repository_file_count": file_count,
    }
