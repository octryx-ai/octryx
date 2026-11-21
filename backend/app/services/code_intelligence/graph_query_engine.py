"""Focused DB-backed query helpers for native Code Graph services."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphChunk, CodeGraphEdge, CodeGraphFile, CodeGraphNode, CodeGraphRoute, CodeGraphSymbol
from app.services.code_intelligence.graph_query_ranking import (
    _bounded_limit,
    _match_kind,
    _relationship_summary,
    _search_score,
)
from app.services.code_intelligence.graph_query_serializers import normalize_direction, serialize_edge, serialize_node
from app.services.code_intelligence.graph_query_support import GraphContext, load_edges, load_nodes_by_ids


async def search_graph_nodes(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    query: str,
    language: str = "",
    path: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip()
    normalized_language = str(language or "").strip()
    normalized_path = str(path or "").strip()
    row_limit = _bounded_limit(limit, default=20)
    stmt = select(CodeGraphNode).where(
        CodeGraphNode.run_id == ctx.run.id,
        CodeGraphNode.is_current.is_(True),
    )
    if normalized_query:
        like = f"%{normalized_query}%"
        stmt = stmt.where(
            or_(
                CodeGraphNode.name.ilike(like),
                CodeGraphNode.external_id.ilike(like),
                CodeGraphNode.path.ilike(like),
                CodeGraphNode.signature.ilike(like),
            )
        )
    if normalized_language:
        stmt = stmt.where(CodeGraphNode.language == normalized_language)
    if normalized_path:
        stmt = stmt.where(CodeGraphNode.path.ilike(f"%{normalized_path}%"))
    rows = (
        await db.execute(stmt.order_by(CodeGraphNode.path.asc(), CodeGraphNode.line_start.asc()).limit(row_limit * 5))
    ).scalars().all()
    file_metadata = await _file_metadata_by_id(db, run_id=ctx.run.id)
    ranked = [
        {
            "node": serialize_node(node),
            "score": _search_score(node, normalized_query, file_metadata.get(node.source_file_id or "", {})),
            "match": _match_kind(node, normalized_query),
            "file_metadata": file_metadata.get(node.source_file_id or "", {}),
        }
        for node in rows
    ]
    return sorted(ranked, key=lambda item: item["score"])[:row_limit]


async def build_node_detail(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    node: CodeGraphNode,
    include_source: bool = False,
    relation_limit: int = 10,
) -> dict[str, Any]:
    row_limit = _bounded_limit(relation_limit, default=10)
    incoming = await load_edges(db, ctx=ctx, node_ids={node.id}, direction="incoming", relation="")
    outgoing = await load_edges(db, ctx=ctx, node_ids={node.id}, direction="outgoing", relation="")
    related_ids = {edge.source_node_id for edge in incoming[:row_limit]} | {
        edge.target_node_id for edge in outgoing[:row_limit]
    }
    related_nodes = await load_nodes_by_ids(db, run_id=ctx.run.id, node_ids=related_ids)
    related_by_id = {item.id: item for item in related_nodes}
    route_bindings = await route_bindings_for_node(db, ctx=ctx, node=node)
    parent = await _parent_node(db, ctx=ctx, node=node)
    children = await _child_nodes(db, ctx=ctx, node=node, limit=row_limit)
    return {
        "parent": serialize_node(parent) if parent else None,
        "children": [serialize_node(child) for child in children],
        "callers": _relationship_summary(incoming, related_by_id, node.id, direction="incoming", relation="calls"),
        "callees": _relationship_summary(outgoing, related_by_id, node.id, direction="outgoing", relation="calls"),
        "references": _relationship_summary(incoming + outgoing, related_by_id, node.id, direction="both", relation=""),
        "route_bindings": route_bindings,
        "source_chunk": await source_chunk_for_node(db, ctx=ctx, node=node) if include_source else None,
        "limits": {"relations": row_limit},
    }


async def related_nodes_for(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    node: CodeGraphNode,
    direction: str,
    relations: set[str],
    limit: int,
) -> dict[str, Any]:
    row_limit = _bounded_limit(limit, default=25)
    edges = await load_edges(
        db,
        ctx=ctx,
        node_ids={node.id},
        direction=normalize_direction(direction),
        relation="",
    )
    filtered = [edge for edge in edges if not relations or edge.relation in relations][:row_limit]
    node_ids: set[str] = set()
    for edge in filtered:
        if edge.source_node_id != node.id:
            node_ids.add(edge.source_node_id)
        if edge.target_node_id != node.id:
            node_ids.add(edge.target_node_id)
    nodes = await load_nodes_by_ids(db, run_id=ctx.run.id, node_ids=node_ids)
    return {
        "nodes": [serialize_node(node) for node in nodes],
        "edges": [serialize_edge(edge) for edge in filtered],
        "count": len(filtered),
        "limits": {"limit": row_limit},
    }


async def route_bindings_for_node(db: AsyncSession, *, ctx: GraphContext, node: CodeGraphNode) -> list[dict[str, Any]]:
    route_edges = await load_edges(db, ctx=ctx, node_ids={node.id}, direction="incoming", relation="routes_to")
    route_node_ids = {edge.source_node_id for edge in route_edges}
    if not route_node_ids:
        return []
    route_nodes = await load_nodes_by_ids(db, run_id=ctx.run.id, node_ids=route_node_ids)
    by_node_id = {item.id: item for item in route_nodes}
    routes = (
        await db.execute(
            select(CodeGraphRoute).where(
                CodeGraphRoute.run_id == ctx.run.id,
                CodeGraphRoute.route_node_id.in_(route_node_ids),
            )
        )
    ).scalars().all()
    return [
        {
            "framework": route.framework,
            "method": route.method,
            "route_path": route.route_path,
            "line_start": route.line_start,
            "confidence": route.confidence,
            "route_node": (
                serialize_node(by_node_id[route.route_node_id]) if route.route_node_id in by_node_id else None
            ),
        }
        for route in routes
    ]


async def source_chunk_for_node(db: AsyncSession, *, ctx: GraphContext, node: CodeGraphNode) -> dict[str, Any] | None:
    symbol = (
        await db.execute(
            select(CodeGraphSymbol).where(
                CodeGraphSymbol.run_id == ctx.run.id,
                CodeGraphSymbol.node_id == node.id,
                CodeGraphSymbol.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    stmt = select(CodeGraphChunk).where(
        CodeGraphChunk.run_id == ctx.run.id,
        CodeGraphChunk.is_current.is_(True),
    )
    if symbol is not None:
        stmt = stmt.where(CodeGraphChunk.source_symbol_id == symbol.id)
    elif node.source_file_id:
        stmt = stmt.where(CodeGraphChunk.source_file_id == node.source_file_id, CodeGraphChunk.chunk_kind == "file")
    else:
        return None
    chunk = (await db.execute(stmt.order_by(CodeGraphChunk.line_start.asc()).limit(1))).scalar_one_or_none()
    if chunk is None:
        return None
    return {
        "chunk_kind": chunk.chunk_kind,
        "path": chunk.path,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "token_estimate": chunk.token_estimate,
    }


async def trace_hops(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    path_nodes: list[CodeGraphNode],
    path_edges: list[CodeGraphEdge],
    include_source: bool = False,
) -> list[dict[str, Any]]:
    hops: list[dict[str, Any]] = []
    for index, node in enumerate(path_nodes):
        hop: dict[str, Any] = {
            "index": index,
            "node": serialize_node(node),
            "via_edge": serialize_edge(path_edges[index - 1]) if index > 0 and index - 1 < len(path_edges) else None,
        }
        if include_source:
            hop["source_chunk"] = await source_chunk_for_node(db, ctx=ctx, node=node)
        hops.append(hop)
    return hops


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


async def _parent_node(db: AsyncSession, *, ctx: GraphContext, node: CodeGraphNode) -> CodeGraphNode | None:
    parent_external_id = str((node.node_metadata or {}).get("parent_external_id") or "").strip()
    if not parent_external_id:
        return None
    return (
        await db.execute(
            select(CodeGraphNode).where(
                CodeGraphNode.run_id == ctx.run.id,
                CodeGraphNode.external_id == parent_external_id,
                CodeGraphNode.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _child_nodes(db: AsyncSession, *, ctx: GraphContext, node: CodeGraphNode, limit: int) -> list[CodeGraphNode]:
    rows = (
        await db.execute(
            select(CodeGraphNode).where(
                CodeGraphNode.run_id == ctx.run.id,
                CodeGraphNode.path == node.path,
                CodeGraphNode.is_current.is_(True),
            )
        )
    ).scalars().all()
    children = [
        item
        for item in rows
        if str((item.node_metadata or {}).get("parent_external_id") or "") == node.external_id
    ]
    return sorted(children, key=lambda item: (item.line_start or 0, item.name or ""))[:limit]


__all__ = [
    "build_node_detail",
    "related_nodes_for",
    "route_bindings_for_node",
    "search_graph_nodes",
    "source_chunk_for_node",
    "trace_hops",
]
