"""File listing and path tracing queries over the native code graph."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphFile, CodeGraphNode
from app.services.code_intelligence.graph_query_engine import trace_hops
from app.services.code_intelligence.graph_query_serializers import (
    missing_graph_response,
    normalize_direction,
    serialize_edge,
    serialize_graph_context,
    serialize_node,
)
from app.services.code_intelligence.graph_query_support import (
    MAX_TRACE_EXPANSIONS,
    MAX_TRAVERSAL_DEPTH,
    GraphContext,
    load_edges_by_ids,
    load_graph_context,
    load_nodes_by_ids,
    resolve_node,
    shortest_path,
)
from app.services.code_intelligence.storage_repository import _serialize_repository

_NO_PATH_REASON = (
    "no static path found; this may be a dynamic-dispatch, reflection, dependency-injection, "
    "or unresolved-reference gap"
)


async def get_code_graph_files(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Any = None,
    project_id: str | None = None,
    language: str | None = None,
    path: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    del cwd
    ctx = await load_graph_context(
        db=db,
        repository_id=repository_id,
        project_id=project_id,
    )
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    stmt = select(CodeGraphFile).where(
        CodeGraphFile.run_id == ctx.run.id,
        CodeGraphFile.is_current.is_(True),
    )
    normalized_language = str(language or "").strip()
    normalized_path = str(path or "").strip()
    if normalized_language:
        stmt = stmt.where(CodeGraphFile.language == normalized_language)
    if normalized_path:
        stmt = stmt.where(CodeGraphFile.file_path.ilike(f"%{normalized_path}%"))
    rows = (
        await db.execute(
            stmt.order_by(CodeGraphFile.file_path.asc()).limit(max(1, min(int(limit or 100), 500)))
        )
    ).scalars().all()
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "ready",
        "files": [_serialize_file_row(row) for row in rows],
        "count": len(rows),
        "filters": {"language": normalized_language, "path": normalized_path},
    }


def _serialize_file_row(row: CodeGraphFile) -> dict[str, Any]:
    return {
        "id": row.id,
        "path": row.file_path,
        "language": row.language,
        "line_count": row.line_count,
        "size_bytes": row.size_bytes,
        "file_hash": row.file_hash,
        "is_stale": bool(row.is_stale),
        "parse_error": row.parse_error,
        "metadata": row.file_metadata or {},
    }


async def get_code_graph_trace(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Any = None,
    project_id: str | None = None,
    source: str | None = None,
    target: str | None = None,
    direction: str = "both",
    max_depth: int = 6,
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
    source_node = await resolve_node(db, ctx=ctx, query=source, node_id=source)
    target_node = await resolve_node(db, ctx=ctx, query=target, node_id=target)
    if source_node is None or target_node is None:
        return _endpoint_response(ctx, "endpoint_not_found", source_node, target_node, path=[])
    if source_node.id == target_node.id:
        return _endpoint_response(ctx, "same_node", source_node, target_node, path=[serialize_node(source_node)])
    return await _traced_path(
        db,
        ctx=ctx,
        source_node=source_node,
        target_node=target_node,
        direction=direction,
        max_depth=max_depth,
        include_source=include_source,
    )


def _endpoint_response(
    ctx: GraphContext,
    status: str,
    source_node: CodeGraphNode | None,
    target_node: CodeGraphNode | None,
    *,
    path: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": status,
        "source_node": serialize_node(source_node) if source_node else None,
        "target_node": serialize_node(target_node) if target_node else None,
        "path": path,
        "edges": [],
    }


async def _traced_path(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    source_node: CodeGraphNode,
    target_node: CodeGraphNode,
    direction: str,
    max_depth: int,
    include_source: bool,
) -> dict[str, Any]:
    depth_cap = max(1, min(int(max_depth or 6), MAX_TRAVERSAL_DEPTH))
    path_ids, edge_ids, truncated = await shortest_path(
        db,
        ctx=ctx,
        source_id=source_node.id,
        target_id=target_node.id,
        direction=normalize_direction(direction),
        max_depth=depth_cap,
    )
    nodes = await load_nodes_by_ids(db, run_id=ctx.run.id, node_ids=set(path_ids))
    node_by_id = {node.id: node for node in nodes}
    edges = await load_edges_by_ids(db, run_id=ctx.run.id, edge_ids=set(edge_ids))
    edge_by_id = {edge.id: edge for edge in edges}
    ordered_nodes = [node_by_id[node_id] for node_id in path_ids if node_id in node_by_id]
    ordered_edges = [edge_by_id[edge_id] for edge_id in edge_ids if edge_id in edge_by_id]
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "ready" if path_ids else "no_path",
        "source_node": serialize_node(source_node),
        "target_node": serialize_node(target_node),
        "path": [serialize_node(node) for node in ordered_nodes],
        "edges": [serialize_edge(edge) for edge in ordered_edges],
        "hops": await trace_hops(
            db, ctx=ctx, path_nodes=ordered_nodes, path_edges=ordered_edges, include_source=include_source
        ),
        "hop_count": max(0, len(path_ids) - 1),
        "truncated": truncated,
        "no_path_reason": "" if path_ids else _NO_PATH_REASON,
        "limits": {"max_depth": depth_cap, "max_expansions": MAX_TRACE_EXPANSIONS},
    }
