"""Serializers and small response helpers for native code graph queries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models import CodeGraphEdge, CodeGraphNode

if TYPE_CHECKING:
    from app.services.code_intelligence.graph_query_support import GraphContext


def serialize_graph_context(ctx: GraphContext) -> dict[str, Any]:
    sync_state = ctx.sync_state or {}
    staleness_state = "stale" if sync_state.get("state") == "stale" else ctx.graph_repository.staleness_state
    return {
        "graph_repository_id": ctx.graph_repository.id,
        "run_id": ctx.run.id,
        "commit_hash": ctx.run.commit_hash,
        "status": ctx.run.status,
        "backend": ctx.run.backend,
        "staleness_state": staleness_state,
        "is_stale": bool(ctx.run.is_stale or sync_state.get("state") == "stale"),
        "staleness_warnings": sync_state.get("warnings") or [],
        "sync": sync_state.get("summary") or {},
        "node_count": int(ctx.run.node_count or 0),
        "edge_count": int(ctx.run.edge_count or 0),
    }


def serialize_node(node: CodeGraphNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "external_id": node.external_id,
        "node_type": node.node_type,
        "name": node.name,
        "language": node.language,
        "signature": node.signature,
        "path": node.path,
        "line_start": node.line_start,
        "line_end": node.line_end,
        "confidence": node.confidence,
        "is_stale": bool(node.is_stale),
        "source_file_id": node.source_file_id,
        "metadata": node.node_metadata or {},
    }


def serialize_edge(edge: CodeGraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "relation": edge.relation,
        "confidence": edge.confidence,
        "is_directed": bool(edge.is_directed),
        "metadata": edge.edge_metadata or {},
    }


def normalize_direction(value: str) -> str:
    direction = str(value or "both").strip().lower()
    return direction if direction in {"incoming", "outgoing", "both"} else "both"


def missing_graph_response(*, repository_id: str | None) -> dict[str, Any]:
    return {
        "repository_id": repository_id or "",
        "graph": {"status": "missing"},
        "status": "graph_not_indexed",
        "nodes": [],
        "edges": [],
    }

