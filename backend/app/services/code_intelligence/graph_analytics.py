"""DB-backed analytics helpers for the native code graph."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphEdge, CodeGraphNode
from app.services.code_intelligence.graph_analytics_counts import (
    _count_by_edge_field,
    _count_by_node_field,
    _rank_nodes_by_degree,
)
from app.services.code_intelligence.graph_query_serializers import (
    missing_graph_response,
    normalize_direction,
    serialize_edge,
    serialize_graph_context,
    serialize_node,
)
from app.services.code_intelligence.graph_query_support import (
    MAX_NODE_LIMIT,
    MAX_TRAVERSAL_DEPTH,
    GraphContext,
    load_edges,
    load_graph_context,
    load_nodes_by_ids,
    resolve_node,
)
from app.services.code_intelligence.storage_repository import _serialize_repository


async def get_code_graph_stats(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Any = None,
    project_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    del cwd
    ctx = await load_graph_context(
        db=db,
        repository_id=repository_id,
        project_id=project_id,
    )
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    row_limit = _bounded_limit(limit, default=10)
    node_types = await _count_by_node_field(db, run_id=ctx.run.id, field=CodeGraphNode.node_type)
    node_confidences = await _count_by_node_field(db, run_id=ctx.run.id, field=CodeGraphNode.confidence)
    relations = await _count_by_edge_field(db, run_id=ctx.run.id, field=CodeGraphEdge.relation)
    edge_confidences = await _count_by_edge_field(db, run_id=ctx.run.id, field=CodeGraphEdge.confidence)
    god_nodes = await _rank_nodes_by_degree(db, run_id=ctx.run.id, limit=row_limit)
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "ready",
        "stats": {
            "node_count": int(ctx.run.node_count or 0),
            "edge_count": int(ctx.run.edge_count or 0),
            "file_count": int(ctx.run.file_count or 0),
            "unresolved_reference_count": int(ctx.run.unresolved_reference_count or 0),
        },
        "node_types": node_types,
        "node_confidences": node_confidences,
        "relations": relations,
        "edge_confidences": edge_confidences,
        "top_degree_nodes": god_nodes,
        "limits": {"top_nodes": row_limit},
    }


async def get_code_graph_god_nodes(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Any = None,
    project_id: str | None = None,
    relation: str | None = None,
    node_type: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    del cwd
    ctx = await load_graph_context(
        db=db,
        repository_id=repository_id,
        project_id=project_id,
    )
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    row_limit = _bounded_limit(limit, default=10)
    nodes = await _rank_nodes_by_degree(
        db,
        run_id=ctx.run.id,
        relation=str(relation or "").strip() or None,
        node_type=str(node_type or "").strip() or None,
        limit=row_limit,
    )
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "ready",
        "nodes": nodes,
        "count": len(nodes),
        "filters": {
            "relation": relation or "",
            "node_type": node_type or "",
        },
        "limits": {"limit": row_limit},
    }


async def get_code_graph_affected(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Any = None,
    project_id: str | None = None,
    node_id: str | None = None,
    query: str | None = None,
    name: str | None = None,
    path: str | None = None,
    relation: str | None = None,
    direction: str = "incoming",
    depth: int = 2,
    max_nodes: int = 50,
) -> dict[str, Any]:
    del cwd
    ctx = await load_graph_context(db=db, repository_id=repository_id, project_id=project_id)
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    start = await resolve_node(db, ctx=ctx, node_id=node_id, query=query, name=name, path=path)
    if start is None:
        return _node_not_found_response(ctx)

    depth_cap = max(1, min(int(depth or 2), MAX_TRAVERSAL_DEPTH))
    node_cap = max(1, min(int(max_nodes or 50), MAX_NODE_LIMIT))
    traversal_direction = normalize_direction(direction or "incoming")
    visited, edge_rows, truncated = await _walk_affected(
        db,
        ctx=ctx,
        start_id=start.id,
        depth_cap=depth_cap,
        node_cap=node_cap,
        direction=traversal_direction,
        relation=str(relation or "").strip(),
    )
    affected_ids = visited - {start.id}
    nodes = await load_nodes_by_ids(db, run_id=ctx.run.id, node_ids=affected_ids)
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "truncated" if truncated else "ready",
        "start_node": serialize_node(start),
        "affected_nodes": [serialize_node(node) for node in nodes],
        "affected_files": _affected_files(nodes),
        "edges": [serialize_edge(edge) for edge in edge_rows.values()],
        "truncated": truncated,
        "semantics": _affected_semantics(traversal_direction),
        "filters": {"relation": relation or "", "direction": traversal_direction},
        "limits": {"depth": depth_cap, "max_nodes": node_cap},
    }


def _node_not_found_response(ctx: GraphContext) -> dict[str, Any]:
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "node_not_found",
        "start_node": None,
        "affected_nodes": [],
        "edges": [],
        "affected_files": [],
    }


async def _walk_affected(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    start_id: str,
    depth_cap: int,
    node_cap: int,
    direction: str,
    relation: str,
) -> tuple[set[str], dict[str, CodeGraphEdge], bool]:
    """Breadth-first walk from the start node, bounded by depth and node count."""
    visited = {start_id}
    frontier = {start_id}
    edge_rows: dict[str, CodeGraphEdge] = {}
    truncated = False

    for _current_depth in range(1, depth_cap + 1):
        if not frontier or len(visited) >= node_cap:
            truncated = truncated or bool(frontier and len(visited) >= node_cap)
            break
        rows = await load_edges(
            db,
            ctx=ctx,
            node_ids=frontier,
            direction=direction,
            relation=relation,
        )
        next_frontier: set[str] = set()
        for edge in rows:
            edge_rows[edge.id] = edge
            for candidate in (edge.source_node_id, edge.target_node_id):
                if candidate in visited:
                    continue
                if len(visited) >= node_cap:
                    truncated = True
                    continue
                visited.add(candidate)
                next_frontier.add(candidate)
        frontier = next_frontier
    return visited, edge_rows, truncated


def _affected_files(nodes: list[CodeGraphNode]) -> list[dict[str, Any]]:
    by_path: dict[str, list[CodeGraphNode]] = defaultdict(list)
    for node in nodes:
        if node.path:
            by_path[node.path].append(node)
    return [
        {
            "path": path,
            "node_count": len(path_nodes),
            "nodes": [
                {
                    "id": node.id,
                    "name": node.name,
                    "node_type": node.node_type,
                    "line_start": node.line_start,
                }
                for node in path_nodes
            ],
        }
        for path, path_nodes in sorted(by_path.items())
    ]


def _affected_semantics(direction: str) -> str:
    if direction == "incoming":
        return "dependents_that_may_be_affected_by_start_changes"
    if direction == "outgoing":
        return "dependencies_used_by_the_start_node"
    return "bidirectional_related_nodes"


def _bounded_limit(value: int, *, default: int) -> int:
    return max(1, min(int(value or default), MAX_NODE_LIMIT))
