"""The bounded subgraph payload in its three entry modes (skeleton, query, focus)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_graph import KnowledgeGraphEdge, KnowledgeGraphNode
from ..retrieval import search_graph_nodes
from .queries import _degrees, _edge_payload, _edges_between, _in_scope, _neighbor_ids, _node_payload, _scoped_totals

MAX_NODES = 400
# Upper bound on matched seeds of one query (the retrieval's own maximum).
MAX_QUERY_MATCHES = 100


async def _focus_seeds(db: AsyncSession, focus_node_id: str, max_nodes: int) -> set[str]:
    seed_ids: set[str] = set()
    node = await db.get(KnowledgeGraphNode, focus_node_id)
    if node is not None and node.status == "active":
        # Ring-by-ring BFS: the full direct neighborhood first, then
        # neighbors-of-neighbors until the node budget is used — a focus
        # on a sparsely connected node still shows its surroundings.
        seed_ids = {node.id}
        frontier = {node.id}
        while frontier and len(seed_ids) < max_nodes:
            ring = await _neighbor_ids(db, frontier, limit=max_nodes - len(seed_ids))
            ring -= seed_ids
            if not ring:
                break
            seed_ids |= ring
            frontier = ring
    return seed_ids


async def _query_seeds(
    db: AsyncSession, query: str, project_ids: list[str] | None, node_types: list[str] | None, max_nodes: int
) -> tuple[set[str], list[str]]:
    """``(seed ids, match ids)``: the real matches of the query plus their neighbourhood."""
    hits = await search_graph_nodes(
        db,
        query=query,
        project_ids=project_ids,
        node_types=node_types,
        limit=min(MAX_QUERY_MATCHES, max_nodes),
        matches_only=True,
    )
    match_ids = [hit["id"] for hit in hits]
    seed_ids = set(match_ids)
    seed_ids |= await _neighbor_ids(db, seed_ids, limit=max_nodes - len(seed_ids))
    return seed_ids, match_ids


async def _skeleton_seeds(
    db: AsyncSession, project_id: str, node_types: list[str] | None, max_nodes: int
) -> set[str]:
    stmt = select(KnowledgeGraphNode.id).where(KnowledgeGraphNode.status == "active")
    if project_id:
        stmt = stmt.where(_in_scope(KnowledgeGraphNode.project_id, project_id))
    if node_types:
        stmt = stmt.where(KnowledgeGraphNode.node_type.in_(node_types))
    all_ids = [row[0] for row in (await db.execute(stmt)).all()]
    degrees = await _degrees(db, all_ids)
    ranked = sorted(all_ids, key=lambda node_id: -degrees.get(node_id, 0))
    return set(ranked[:max_nodes])


async def _shown_nodes(
    db: AsyncSession,
    *,
    seed_ids: set[str],
    match_ids: list[str] | None,
    project_id: str,
    node_types: list[str] | None,
    focus_node_id: str,
    max_nodes: int,
    exclude_project_ids: frozenset[str],
) -> list[KnowledgeGraphNode]:
    node_stmt = select(KnowledgeGraphNode).where(
        KnowledgeGraphNode.id.in_(seed_ids),
        KnowledgeGraphNode.status == "active",
    )
    if exclude_project_ids:
        node_stmt = node_stmt.where(or_(KnowledgeGraphNode.project_id.is_(None),
                                        KnowledgeGraphNode.project_id.not_in(sorted(exclude_project_ids))))
    if project_id:
        # Neighbours are found over edges, which may cross into another project's nodes.
        node_stmt = node_stmt.where(_in_scope(KnowledgeGraphNode.project_id, project_id))
    nodes = list((await db.execute(node_stmt)).scalars().all())
    if match_ids is not None:
        # Matches first, so the node budget never drops a match in favour of a neighbour.
        rank = {node_id: index for index, node_id in enumerate(match_ids)}
        nodes.sort(key=lambda node: rank.get(node.id, len(rank)))
    if node_types and not focus_node_id:
        allowed = {str(t).strip().lower() for t in node_types}
        nodes = [node for node in nodes if node.node_type in allowed]
    return nodes[:max_nodes]


def _type_counts(nodes: list[KnowledgeGraphNode], edges: list[KnowledgeGraphEdge]) -> dict[str, dict[str, int]]:
    type_counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        type_counts[node.node_type] += 1
    edge_type_counts: dict[str, int] = defaultdict(int)
    for edge in edges:
        edge_type_counts[edge.edge_type] += 1
    return {
        "node_types": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
        "edge_types": dict(sorted(edge_type_counts.items(), key=lambda kv: -kv[1])),
    }


async def build_entity_graph(
    db: AsyncSession,
    *,
    project_id: str = "",
    query: str = "",
    node_types: list[str] | None = None,
    focus_node_id: str = "",
    max_nodes: int = 150,
    exclude_project_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """``exclude_project_ids``: Workspaces whose nodes never appear (private ones for the admin view)."""
    max_nodes = max(10, min(int(max_nodes or 150), MAX_NODES))
    project_ids = [project_id] if project_id else None
    seed_ids: set[str] = set()
    match_ids: list[str] | None = None

    if focus_node_id:
        seed_ids = await _focus_seeds(db, focus_node_id, max_nodes)
    elif query.strip():
        seed_ids, match_ids = await _query_seeds(db, query, project_ids, node_types, max_nodes)
    else:
        seed_ids = await _skeleton_seeds(db, project_id, node_types, max_nodes)

    nodes = await _shown_nodes(
        db, seed_ids=seed_ids, match_ids=match_ids, project_id=project_id, node_types=node_types,
        focus_node_id=focus_node_id, max_nodes=max_nodes, exclude_project_ids=exclude_project_ids,
    )
    node_ids = {node.id for node in nodes}
    degrees = await _degrees(db, list(node_ids))
    edges = await _edges_between(db, node_ids)
    counts = _type_counts(nodes, edges)

    totals = await _scoped_totals(db, project_id)
    matched = set(match_ids or ())
    shown_matches = [node.id for node in nodes if node.id in matched]

    return {
        "nodes": [_node_payload(node, degrees.get(node.id, 0), matched=node.id in matched) for node in nodes],
        "edges": [_edge_payload(edge) for edge in edges],
        # ``None`` without a query; a list (possibly empty) when a query was given.
        "match_ids": shown_matches if match_ids is not None else None,
        "stats": {
            "shown_nodes": len(nodes),
            "shown_edges": len(edges),
            "matched_nodes": len(shown_matches) if match_ids is not None else None,
            "match_limit": MAX_QUERY_MATCHES,
            "scope": "project" if project_id else "instance",
            **totals,
            **counts,
        },
    }
