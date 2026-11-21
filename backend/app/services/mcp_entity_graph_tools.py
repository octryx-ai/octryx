"""Entity-graph tool handlers for the MCP protocol server.

The knowledge graph is the PRIMARY knowledge surface: entities and relations
each carry their own ``trust_level`` (bronze evidence, silver once multiple
independent sources or a review confirm it, gold as an explicit act). These
tools expose the graph read-only under the existing ``knowledge:read`` scope
so MCP clients can answer "who/what is X connected to" questions that
entry-level search cannot.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..models.project.knowledge_graph import KnowledgeGraphEdge, KnowledgeGraphNode
from .knowledge_graph.retrieval import search_graph_nodes

MAX_ENTITY_RESULTS = 25
MAX_NEIGHBOR_RESULTS = 50

_TRUST_NOTE = (
    "trust_level is evidence-based per node/edge: bronze = single source, "
    "silver = multi-source confirmed or review-approved, gold = curated."
)


def _node_payload(node: KnowledgeGraphNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "node_type": node.node_type,
        "node_key": node.node_key,
        "display_name": node.display_name,
        "trust_level": node.trust_level,
        "status": node.status,
        "description": (node.description or "")[:300],
        "evidence_count": len(node.source_refs or []),
    }


async def _readable_projects(db: AsyncSession, user: User) -> set[str]:
    """The caller's own Workspaces (membership; private only their own, no admin shortcut). A
    ``project_id`` argument outside them is refused; without one, only these are searched."""
    from .project import get_user_project_ids  # noqa: PLC0415

    return set(await get_user_project_ids(str(user.id), db))


def _readable(node: KnowledgeGraphNode | None, readable: set[str]) -> bool:
    return node is not None and (node.project_id is None or node.project_id in readable)


async def mcp_entity_search(db: AsyncSession, *, user: User, arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = str(arguments.get("project_id") or "").strip()
    readable = await _readable_projects(db, user)
    if project_id and project_id not in readable:
        return {"error": "Workspace not found or not accessible"}
    scope = [project_id] if project_id else (sorted(readable) or ["-"])  # instance-global knowledge stays in
    query = str(arguments.get("query") or "").strip()
    node_type = str(arguments.get("node_type") or "").strip()
    limit = max(1, min(int(arguments.get("limit") or 10), MAX_ENTITY_RESULTS))
    # Ranked graph retrieval first: alias-based entity linking + embedding +
    # keyword signal — the same scorer the platform retrieval uses.
    ranked = await search_graph_nodes(
        db,
        query=query,
        project_ids=scope,
        node_types=[node_type] if node_type else None,
        limit=limit,
        alias_query=query,
    )
    if ranked:
        items = [
            {
                "id": node.get("id"),
                "node_type": node.get("node_type"),
                "display_name": node.get("display_name"),
                "trust_level": node.get("trust_level") or "bronze",
                "description": str(node.get("description") or "")[:300],
                "evidence_count": len(node.get("source_refs") or []),
                "score": node.get("score"),
            }
            for node in ranked
        ]
        return {"items": items, "ranking": "graph_retrieval", "note": _TRUST_NOTE}
    # Substring fallback catches partial identifiers that no alias or
    # embedding covers (e.g. a fragment of a repo slug).
    stmt = select(KnowledgeGraphNode).where(KnowledgeGraphNode.status == "active")
    stmt = stmt.where(or_(KnowledgeGraphNode.project_id.in_(scope), KnowledgeGraphNode.project_id.is_(None)))
    if node_type:
        stmt = stmt.where(KnowledgeGraphNode.node_type == node_type)
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            or_(
                KnowledgeGraphNode.display_name.ilike(pattern),
                KnowledgeGraphNode.node_key.ilike(pattern),
            )
        )
    rows = (await db.execute(stmt.order_by(KnowledgeGraphNode.updated_at.desc()).limit(limit))).scalars().all()
    return {
        "items": [_node_payload(node) for node in rows],
        "ranking": "substring_fallback",
        "note": _TRUST_NOTE,
    }


async def mcp_entity_neighbors(db: AsyncSession, *, user: User, arguments: dict[str, Any]) -> dict[str, Any]:
    node_ref = str(arguments.get("node") or "").strip()
    if not node_ref:
        return {"error": "node (id, node_key, or display name) is required"}
    limit = max(1, min(int(arguments.get("limit") or 25), MAX_NEIGHBOR_RESULTS))
    node = await db.get(KnowledgeGraphNode, node_ref)
    if node is None:
        node = (
            await db.execute(
                select(KnowledgeGraphNode)
                .where(
                    or_(
                        func.lower(KnowledgeGraphNode.node_key) == node_ref.lower(),
                        func.lower(KnowledgeGraphNode.display_name) == node_ref.lower(),
                    )
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    if node is None:
        # The alias table is the canonical identity map (usernames, ticket
        # keys, repo slugs) - resolve through it before giving up.
        from ..models.project.knowledge_graph import KnowledgeGraphAlias
        from .knowledge_graph.store import normalize_alias

        alias_row = (
            await db.execute(
                select(KnowledgeGraphAlias)
                .where(KnowledgeGraphAlias.normalized_alias == normalize_alias(node_ref))
                .limit(1)
            )
        ).scalar_one_or_none()
        if alias_row is not None:
            node = await db.get(KnowledgeGraphNode, alias_row.node_id)
    readable = await _readable_projects(db, user)
    if not _readable(node, readable):
        return {"error": f"Entity not found: {node_ref}"}
    edges = (
        await db.execute(
            select(KnowledgeGraphEdge)
            .where(or_(KnowledgeGraphEdge.source_node_id == node.id, KnowledgeGraphEdge.target_node_id == node.id))
            .limit(limit)
        )
    ).scalars().all()
    neighbor_ids = {
        edge.target_node_id if edge.source_node_id == node.id else edge.source_node_id for edge in edges
    }
    neighbors = {}
    if neighbor_ids:
        rows = (
            await db.execute(select(KnowledgeGraphNode).where(KnowledgeGraphNode.id.in_(neighbor_ids)))
        ).scalars().all()
        neighbors = {row.id: row for row in rows if _readable(row, readable)}
    relations = []
    for edge in edges:
        other_id = edge.target_node_id if edge.source_node_id == node.id else edge.source_node_id
        other = neighbors.get(other_id)
        if other is None:
            continue
        relations.append(
            {
                "edge_type": edge.edge_type,
                "direction": "out" if edge.source_node_id == node.id else "in",
                "trust_level": edge.trust_level,
                "evidence_count": len(edge.source_refs or []),
                "description": (edge.description or "")[:200],
                "neighbor": _node_payload(other),
            }
        )
    return {"entity": _node_payload(node), "relations": relations, "relation_count": len(relations)}


MCP_ENTITY_GRAPH_TOOL_HANDLERS = {
    "entity_search": mcp_entity_search,
    "entity_neighbors": mcp_entity_neighbors,
}


def register_entity_graph_tools(server: Any, call: Any) -> None:
    """Register graph tools; ``call`` is the authenticated knowledge dispatch."""

    @server.tool(
        description=(
            "Search knowledge-graph entities (person, repository, system, ticket, concept, ...) "
            "by name/key. Returns per-node trust_level - the graph is not the gold layer."
        )
    )
    async def entity_search(
        query: str,
        project_id: str = "",
        node_type: str = "",
        limit: int = 10,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "entity_search",
            {"query": query, "project_id": project_id, "node_type": node_type, "limit": limit},
        )

    @server.tool(
        description="Load an entity's graph neighborhood (edges + neighbor nodes) by id, node_key, or display name."
    )
    async def entity_neighbors(node: str, limit: int = 25, ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "entity_neighbors", {"node": node, "limit": limit})


__all__ = ["MCP_ENTITY_GRAPH_TOOL_HANDLERS", "register_entity_graph_tools"]
