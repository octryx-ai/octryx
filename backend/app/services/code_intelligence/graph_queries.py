"""DB-backed query helpers for the native code graph."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphEdge
from app.services.code_intelligence.graph_query_engine import build_node_detail, search_graph_nodes
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
    find_nodes,
    load_edges,
    load_graph_context,
    load_nodes_by_ids,
    resolve_node,
)
from app.services.code_intelligence.storage_repository import _serialize_repository


async def get_code_graph_node(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Any = None,
    project_id: str | None = None,
    node_id: str | None = None,
    query: str | None = None,
    name: str | None = None,
    path: str | None = None,
    limit: int = 10,
    include_source: bool = False,
) -> dict[str, Any]:
    del cwd
    ctx = await load_graph_context(
        db=db,
        repository_id=repository_id,
        project_id=project_id,
    )
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    nodes = await find_nodes(
        db,
        ctx=ctx,
        node_id=node_id,
        query=query,
        name=name,
        path=path,
        limit=limit,
    )
    node = nodes[0] if nodes else None
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "node": serialize_node(node) if node else None,
        "detail": await build_node_detail(
            db,
            ctx=ctx,
            node=node,
            include_source=include_source,
            relation_limit=limit,
        )
        if node
        else {},
        "matches": [serialize_node(node) for node in nodes],
        "match_count": len(nodes),
        "query": {
            "node_id": node_id or "",
            "query": query or "",
            "name": name or "",
            "path": path or "",
        },
    }


async def get_code_graph_search(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Any = None,
    project_id: str | None = None,
    query: str,
    language: str | None = None,
    path: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    del cwd
    ctx = await load_graph_context(
        db=db,
        repository_id=repository_id,
        project_id=project_id,
    )
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    matches = await search_graph_nodes(
        db,
        ctx=ctx,
        query=query,
        language=str(language or "").strip(),
        path=str(path or "").strip(),
        limit=limit,
    )
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "ready",
        "query": query,
        "matches": matches,
        "count": len(matches),
        "filters": {"language": language or "", "path": path or ""},
        "limits": {"limit": max(1, min(int(limit or 20), MAX_NODE_LIMIT))},
    }


async def get_code_graph_status(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Any = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    del cwd
    ctx = await load_graph_context(
        db=db,
        repository_id=repository_id,
        project_id=project_id,
    )
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    graph = serialize_graph_context(ctx)
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": graph,
        "graph_backend": ctx.run.backend,
        "status": graph["staleness_state"],
        "staleness_warnings": graph["staleness_warnings"],
        "latest_run": {
            "id": ctx.run.id,
            "status": ctx.run.status,
            "trigger": ctx.run.trigger,
            "backend": ctx.run.backend,
            "file_count": int(ctx.run.file_count or 0),
            "node_count": int(ctx.run.node_count or 0),
            "edge_count": int(ctx.run.edge_count or 0),
            "unresolved_reference_count": int(ctx.run.unresolved_reference_count or 0),
            "duration_ms": ctx.run.duration_ms,
            "is_stale": bool(ctx.run.is_stale),
            "staleness_reason": ctx.run.staleness_reason,
            "error": ctx.run.error,
            "started_at": ctx.run.started_at.isoformat() if ctx.run.started_at else None,
            "finished_at": ctx.run.finished_at.isoformat() if ctx.run.finished_at else None,
            "metadata": ctx.run.run_metadata or {},
        },
    }


async def get_code_graph_neighbors(
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
    depth: int = 1,
    max_nodes: int = 25,
) -> dict[str, Any]:
    del cwd
    ctx = await load_graph_context(
        db=db,
        repository_id=repository_id,
        project_id=project_id,
    )
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    start = await resolve_node(db, ctx=ctx, node_id=node_id, query=query, name=name, path=path)
    if start is None:
        return {
            "repository": _serialize_repository(ctx.repository),
            "graph": serialize_graph_context(ctx),
            "graph_backend": ctx.run.backend,
            "start_node": None,
            "nodes": [],
            "edges": [],
            "status": "node_not_found",
        }

    depth_cap = max(0, min(int(depth or 1), MAX_TRAVERSAL_DEPTH))
    node_cap = max(1, min(int(max_nodes or 25), MAX_NODE_LIMIT))
    visited, edge_rows, truncated = await _expand_neighbors(
        db,
        ctx=ctx,
        start_id=start.id,
        depth_cap=depth_cap,
        node_cap=node_cap,
        direction=normalize_direction(direction),
        relation=str(relation or "").strip(),
    )
    nodes = await load_nodes_by_ids(db, run_id=ctx.run.id, node_ids=visited)
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "start_node": serialize_node(start),
        "nodes": [serialize_node(node) for node in nodes],
        "edges": [serialize_edge(edge) for edge in edge_rows.values()],
        "status": "truncated" if truncated else "ready",
        "truncated": truncated,
        "limits": {"depth": depth_cap, "max_nodes": node_cap},
    }


async def _expand_neighbors(
    db: AsyncSession | None,
    *,
    ctx: Any,
    start_id: str,
    depth_cap: int,
    node_cap: int,
    direction: str,
    relation: str,
) -> tuple[set[str], dict[str, CodeGraphEdge], bool]:
    visited = {start_id}
    frontier = {start_id}
    edge_rows: dict[str, CodeGraphEdge] = {}
    truncated = False
    for _ in range(depth_cap):
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


async def get_code_graph_callees(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Any = None,
    project_id: str | None = None,
    node_id: str | None = None,
    query: str | None = None,
    name: str | None = None,
    path: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    result = await get_code_graph_neighbors(
        db=db,
        repository_id=repository_id,
        cwd=cwd,
        project_id=project_id,
        node_id=node_id,
        query=query,
        name=name,
        path=path,
        relation="calls",
        direction="outgoing",
        depth=1,
        max_nodes=limit,
    )
    start_id = result.get("start_node", {}).get("id") if isinstance(result.get("start_node"), dict) else None
    result["callees"] = [node for node in result.get("nodes", []) if node.get("id") != start_id]
    result["semantics"] = "direct_static_callees_from_start_node"
    return result

