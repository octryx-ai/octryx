"""Budgeted native code graph context retrieval."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphEdge
from app.services.code_intelligence.graph_context_selection import build_budgeted_context
from app.services.code_intelligence.graph_query_serializers import (
    missing_graph_response,
    normalize_direction,
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

# Selection fields copied into the response, in response order.
_SELECTION_KEYS = (
    "context_nodes",
    "context_edges",
    "context_files",
    "relationship_map",
    "not_shown_candidates",
    "budget",
)


async def get_code_graph_context(
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
    direction: str = "both",
    depth: int = 2,
    max_nodes: int = 50,
    budget_chars: int = 6000,
) -> dict[str, Any]:
    del cwd
    ctx = await load_graph_context(db=db, repository_id=repository_id, project_id=project_id)
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    start = await resolve_node(db, ctx=ctx, node_id=node_id, query=query, name=name, path=path)
    if start is None:
        return _node_not_found_response(ctx)

    depth_cap = max(0, min(int(depth or 2), MAX_TRAVERSAL_DEPTH))
    node_cap = max(1, min(int(max_nodes or 50), MAX_NODE_LIMIT))
    traversal_direction = normalize_direction(direction)
    visited, depth_by_node, edge_rows, truncated = await _expand_context(
        db,
        ctx=ctx,
        start_id=start.id,
        depth_cap=depth_cap,
        node_cap=node_cap,
        direction=traversal_direction,
        relation=str(relation or "").strip(),
    )
    nodes = await load_nodes_by_ids(db, run_id=ctx.run.id, node_ids=visited)
    selection = await build_budgeted_context(
        db,
        ctx=ctx,
        start=start,
        nodes=nodes,
        edges=list(edge_rows.values()),
        depth_by_node=depth_by_node,
        query=query or name or path or node_id,
        requested_budget_chars=int(budget_chars or 0),
    )
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "truncated" if truncated or selection["truncated"] else "ready",
        "start_node": serialize_node(start),
        **{key: selection[key] for key in _SELECTION_KEYS},
        "truncated": bool(truncated or selection["truncated"]),
        "retrieval_provenance": selection["retrieval_provenance"],
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
        "context_nodes": [],
        "context_edges": [],
        "context_files": [],
    }


async def _expand_context(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    start_id: str,
    depth_cap: int,
    node_cap: int,
    direction: str,
    relation: str,
) -> tuple[set[str], dict[str, int], dict[str, CodeGraphEdge], bool]:
    visited = {start_id}
    frontier = {start_id}
    depth_by_node = {start_id: 0}
    edge_rows: dict[str, CodeGraphEdge] = {}
    truncated = False

    for current_depth in range(1, depth_cap + 1):
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
                depth_by_node[candidate] = current_depth
                next_frontier.add(candidate)
        frontier = next_frontier
    return visited, depth_by_node, edge_rows, truncated
