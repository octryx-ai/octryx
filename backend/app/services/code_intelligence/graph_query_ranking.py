"""Ranking, relation summaries and limits shared by the native Code Graph query engine."""

from __future__ import annotations

from typing import Any

from app.models import CodeGraphEdge, CodeGraphNode
from app.services.code_intelligence.graph_query_serializers import serialize_edge, serialize_node

QUERY_RESULT_LIMIT = 50


def _relationship_summary(
    edges: list[CodeGraphEdge],
    node_by_id: dict[str, CodeGraphNode],
    current_node_id: str,
    *,
    direction: str,
    relation: str,
) -> list[dict[str, Any]]:
    rows = []
    for edge in edges:
        if relation and edge.relation != relation:
            continue
        related_id = edge.source_node_id if edge.target_node_id == current_node_id else edge.target_node_id
        related = node_by_id.get(related_id)
        if related is None:
            continue
        rows.append(
            {
                "node": serialize_node(related),
                "edge": serialize_edge(edge),
                "direction": direction,
                "semantics": _edge_semantics(edge),
            }
        )
    return rows


def _search_score(node: CodeGraphNode, query: str, file_metadata: dict[str, Any]) -> tuple[int, int, str, int, str]:
    text = query.lower()
    qualified = str((node.node_metadata or {}).get("qualified_name") or "").lower()
    name = str(node.name or "").lower()
    external_id = str(node.external_id or "").lower()
    penalty = 0
    if file_metadata.get("is_generated"):
        penalty += 10
    if file_metadata.get("is_vendor"):
        penalty += 8
    if file_metadata.get("is_test"):
        penalty += 3
    if text and text in {name, qualified, external_id}:
        rank = 0
    elif text and (name.startswith(text) or qualified.startswith(text)):
        rank = 1
    elif text and (text in name or text in qualified or text in external_id):
        rank = 2
    else:
        rank = 5
    return (rank, penalty, node.path or "", node.line_start or 0, node.name or "")


def _match_kind(node: CodeGraphNode, query: str) -> str:
    text = query.lower()
    qualified = str((node.node_metadata or {}).get("qualified_name") or "").lower()
    if text and text == str(node.name or "").lower():
        return "exact_name"
    if text and text == qualified:
        return "exact_qualified_name"
    if text and text in str(node.external_id or "").lower():
        return "external_id"
    return "fuzzy"


def _edge_semantics(edge: CodeGraphEdge) -> str:
    if edge.relation == "calls":
        return "direct_static_call" if edge.confidence == "EXTRACTED" else "resolved_call"
    if edge.relation == "routes_to":
        return "route_binding"
    if edge.relation == "imports":
        return "module_dependency"
    return "graph_reference"


def _bounded_limit(value: int, *, default: int) -> int:
    return max(1, min(int(value or default), QUERY_RESULT_LIMIT))
