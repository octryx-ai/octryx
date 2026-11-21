"""Shared support helpers for native code graph queries."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphEdge, CodeGraphNode, CodeGraphRepository, CodeGraphRun

# Serializers live in their own module; they stay importable from here for existing callers.
from app.services.code_intelligence.graph_sync import load_graph_staleness_warnings
from app.services.code_intelligence.repository import get_code_repository
from app.services.code_intelligence.storage_runtime import _normalize_path
from app.services.project_resource_policy import require_repository_operation

MAX_NODE_LIMIT = 50
MAX_TRACE_EXPANSIONS = 500
MAX_TRAVERSAL_DEPTH = 6


@dataclass(frozen=True)
class GraphContext:
    repository: Any
    graph_repository: CodeGraphRepository
    run: CodeGraphRun
    sync_state: dict[str, Any]


async def load_graph_context(
    *, db: AsyncSession | None, repository_id: str | None, project_id: str | None
) -> GraphContext | None:
    if db is None:
        raise HTTPException(status_code=400, detail="Database session is required")
    normalized_repository_id = str(repository_id or "").strip()
    if not normalized_repository_id:
        raise HTTPException(
            status_code=400,
            detail="repository_id is required for native code graph queries",
        )
    repository = await get_code_repository(db, normalized_repository_id)
    if project_id and repository.project_id and repository.project_id != project_id:
        raise HTTPException(status_code=403, detail="Repository is not readable from the current project")
    require_repository_operation(repository, "read")
    graph_repo = (
        await db.execute(
            select(CodeGraphRepository).where(
                CodeGraphRepository.code_repository_id == normalized_repository_id
            )
        )
    ).scalar_one_or_none()
    if graph_repo is None:
        return None
    run = None
    if graph_repo.latest_run_id:
        run = await db.get(CodeGraphRun, graph_repo.latest_run_id)
    if run is None:
        run = (
            await db.execute(
                select(CodeGraphRun)
                .where(CodeGraphRun.graph_repository_id == graph_repo.id)
                .order_by(CodeGraphRun.started_at.desc())
            )
        ).scalar_one_or_none()
    if run is None:
        return None
    sync_state: dict[str, Any] = {"state": "fresh", "warnings": [], "summary": {}}
    repo_root = _normalize_path(repository.repo_root)
    if repo_root.exists() and repo_root.is_dir():
        sync_state = await load_graph_staleness_warnings(
            db=db,
            repository_id=normalized_repository_id,
            repo_root=repo_root,
        )
    return GraphContext(repository=repository, graph_repository=graph_repo, run=run, sync_state=sync_state)


async def resolve_node(db: AsyncSession, *, ctx: GraphContext, **query: Any) -> CodeGraphNode | None:
    nodes = await find_nodes(db, ctx=ctx, limit=1, **query)
    return nodes[0] if nodes else None


async def find_nodes(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    node_id: str | None = None,
    query: str | None = None,
    name: str | None = None,
    path: str | None = None,
    limit: int = 10,
) -> list[CodeGraphNode]:
    stmt = select(CodeGraphNode).where(
        CodeGraphNode.run_id == ctx.run.id,
        CodeGraphNode.is_current.is_(True),
    )
    clauses = []
    normalized_id = str(node_id or "").strip()
    normalized_name = str(name or "").strip()
    normalized_path = str(path or "").strip()
    normalized_query = str(query or "").strip()
    if normalized_id:
        clauses.append(or_(CodeGraphNode.id == normalized_id, CodeGraphNode.external_id == normalized_id))
    if normalized_name:
        clauses.append(CodeGraphNode.name.ilike(f"%{normalized_name}%"))
    if normalized_path:
        clauses.append(CodeGraphNode.path.ilike(f"%{normalized_path}%"))
    if normalized_query:
        like = f"%{normalized_query}%"
        clauses.append(
            or_(
                CodeGraphNode.name.ilike(like),
                CodeGraphNode.external_id.ilike(like),
                CodeGraphNode.path.ilike(like),
            )
        )
    if clauses:
        stmt = stmt.where(or_(*clauses))
    stmt = stmt.limit(max(1, min(int(limit or 10), MAX_NODE_LIMIT)))
    rows = (await db.execute(stmt)).scalars().all()
    sort_query = normalized_id or normalized_name or normalized_path or normalized_query
    return sorted(rows, key=lambda node: _node_score(node, sort_query))


async def load_edges(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    node_ids: set[str],
    direction: str,
    relation: str,
) -> list[CodeGraphEdge]:
    clauses = []
    if direction in {"outgoing", "both"}:
        clauses.append(CodeGraphEdge.source_node_id.in_(node_ids))
    if direction in {"incoming", "both"}:
        clauses.append(CodeGraphEdge.target_node_id.in_(node_ids))
    if not clauses:
        return []
    stmt = select(CodeGraphEdge).where(
        CodeGraphEdge.run_id == ctx.run.id,
        CodeGraphEdge.is_current.is_(True),
        or_(*clauses),
    )
    if relation:
        stmt = stmt.where(CodeGraphEdge.relation == relation)
    return list((await db.execute(stmt.limit(500))).scalars().all())


async def shortest_path(
    db: AsyncSession,
    *,
    ctx: GraphContext,
    source_id: str,
    target_id: str,
    direction: str,
    max_depth: int,
) -> tuple[list[str], list[str], bool]:
    queue: deque[tuple[str, int]] = deque([(source_id, 0)])
    parents: dict[str, tuple[str, str]] = {}
    visited = {source_id}
    expansions = 0
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        expansions += 1
        if expansions > MAX_TRACE_EXPANSIONS:
            return [], [], True
        for edge in await load_edges(db, ctx=ctx, node_ids={current}, direction=direction, relation=""):
            neighbor = edge.target_node_id if edge.source_node_id == current else edge.source_node_id
            if neighbor in visited:
                continue
            parents[neighbor] = (current, edge.id)
            if neighbor == target_id:
                node_path, edge_path = _reconstruct_path(
                    source_id=source_id,
                    target_id=target_id,
                    parents=parents,
                )
                return node_path, edge_path, False
            visited.add(neighbor)
            queue.append((neighbor, depth + 1))
    return [], [], False


def _reconstruct_path(
    *, source_id: str, target_id: str, parents: dict[str, tuple[str, str]]
) -> tuple[list[str], list[str]]:
    nodes = [target_id]
    edges: list[str] = []
    current = target_id
    while current != source_id:
        parent, edge_id = parents[current]
        edges.append(edge_id)
        nodes.append(parent)
        current = parent
    nodes.reverse()
    edges.reverse()
    return nodes, edges


async def load_nodes_by_ids(db: AsyncSession, *, run_id: str, node_ids: set[str]) -> list[CodeGraphNode]:
    if not node_ids:
        return []
    rows = (
        await db.execute(
            select(CodeGraphNode).where(
                CodeGraphNode.run_id == run_id,
                CodeGraphNode.id.in_(node_ids),
            )
        )
    ).scalars().all()
    return sorted(rows, key=lambda node: (node.path or "", node.line_start or 0, node.name or ""))


async def load_edges_by_ids(db: AsyncSession, *, run_id: str, edge_ids: set[str]) -> list[CodeGraphEdge]:
    if not edge_ids:
        return []
    return list(
        (
            await db.execute(
                select(CodeGraphEdge).where(
                    CodeGraphEdge.run_id == run_id,
                    CodeGraphEdge.id.in_(edge_ids),
                )
            )
        )
        .scalars()
        .all()
    )


def _node_score(node: CodeGraphNode, query: str) -> tuple[int, str, int, str]:
    text = str(query or "").strip().lower()
    if not text:
        return (5, node.path or "", node.line_start or 0, node.name or "")
    candidates = [node.id, node.external_id, node.name, node.path or ""]
    lowered = [str(item or "").lower() for item in candidates]
    if text in lowered:
        return (0, node.path or "", node.line_start or 0, node.name or "")
    if any(item.startswith(text) for item in lowered):
        return (1, node.path or "", node.line_start or 0, node.name or "")
    return (2, node.path or "", node.line_start or 0, node.name or "")
