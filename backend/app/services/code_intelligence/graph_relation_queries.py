"""DB-backed relation query services for the native Code Graph."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.code_intelligence.graph_query_engine import related_nodes_for
from app.services.code_intelligence.graph_query_serializers import (
    missing_graph_response,
    serialize_graph_context,
    serialize_node,
)
from app.services.code_intelligence.graph_query_support import load_graph_context, resolve_node
from app.services.code_intelligence.storage_repository import _serialize_repository


async def get_code_graph_callers(
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
    del cwd
    ctx = await load_graph_context(db=db, repository_id=repository_id, project_id=project_id)
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    start = await resolve_node(db, ctx=ctx, node_id=node_id, query=query, name=name, path=path)
    if start is None:
        return _missing_start_response(ctx=ctx, kind="callers")
    related = await related_nodes_for(
        db,
        ctx=ctx,
        node=start,
        direction="incoming",
        relations={"calls", "routes_to", "references"},
        limit=limit,
    )
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "ready",
        "start_node": serialize_node(start),
        "callers": related["nodes"],
        "edges": related["edges"],
        "semantics": "direct_static_callers_and_route_bindings_to_start_node",
        "limits": related["limits"],
    }


async def get_code_graph_references(
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
    del cwd
    ctx = await load_graph_context(db=db, repository_id=repository_id, project_id=project_id)
    if ctx is None:
        return missing_graph_response(repository_id=repository_id)
    start = await resolve_node(db, ctx=ctx, node_id=node_id, query=query, name=name, path=path)
    if start is None:
        return _missing_start_response(ctx=ctx, kind="references")
    related = await related_nodes_for(
        db,
        ctx=ctx,
        node=start,
        direction="both",
        relations={"calls", "references", "imports", "routes_to", "tested_by"},
        limit=limit,
    )
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "ready",
        "start_node": serialize_node(start),
        "references": related["nodes"],
        "edges": related["edges"],
        "semantics": "bounded_static_graph_references_for_start_node",
        "limits": related["limits"],
    }


def _missing_start_response(*, ctx: Any, kind: str) -> dict[str, Any]:
    return {
        "repository": _serialize_repository(ctx.repository),
        "graph": serialize_graph_context(ctx),
        "graph_backend": ctx.run.backend,
        "status": "node_not_found",
        "start_node": None,
        kind: [],
        "edges": [],
    }


__all__ = ["get_code_graph_callers", "get_code_graph_references"]
