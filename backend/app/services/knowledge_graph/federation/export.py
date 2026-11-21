"""Export a bounded subgraph as an unsigned portable package."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_graph import (
    KnowledgeClaim,
    KnowledgeGraphAlias,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
)
from ....time_utils import utc_now
from .package import ENTITY_GRAPH_PACKAGE_FORMAT, MAX_EXPORT_NODES, _node_ref


async def _selected_nodes(
    db: AsyncSession, project_id: str | None, node_types: list[str] | None, max_nodes: int
) -> list[KnowledgeGraphNode]:
    stmt = select(KnowledgeGraphNode).where(KnowledgeGraphNode.status == "active")
    if project_id:
        stmt = stmt.where(KnowledgeGraphNode.project_id == project_id)
    else:
        stmt = stmt.where(KnowledgeGraphNode.project_id.is_(None))
    if node_types:
        stmt = stmt.where(KnowledgeGraphNode.node_type.in_([str(t).strip().lower() for t in node_types]))
    return list((await db.execute(stmt.limit(max_nodes))).scalars().all())


async def _aliases_by_node(db: AsyncSession, node_ids: list[str]) -> dict[str, list[str]]:
    aliases_by_node: dict[str, list[str]] = {}
    if node_ids:
        rows = await db.execute(
            select(KnowledgeGraphAlias.node_id, KnowledgeGraphAlias.alias_value).where(
                KnowledgeGraphAlias.node_id.in_(node_ids)
            )
        )
        for node_id, alias_value in rows.all():
            aliases_by_node.setdefault(node_id, []).append(str(alias_value))
    return aliases_by_node


async def _claims_by_node(db: AsyncSession, node_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    claims_by_node: dict[str, list[dict[str, Any]]] = {}
    if node_ids:
        claims = (
            (
                await db.execute(
                    select(KnowledgeClaim).where(
                        KnowledgeClaim.subject_node_id.in_(node_ids),
                        KnowledgeClaim.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        for claim in claims:
            claims_by_node.setdefault(claim.subject_node_id, []).append(
                {
                    "claim_type": claim.claim_type,
                    "statement": claim.statement,
                    "valid_from_label": claim.valid_from_label,
                    "valid_until_label": claim.valid_until_label,
                }
            )
    return claims_by_node


async def _edges_payload(db: AsyncSession, node_ids: list[str], ref_by_id: dict[str, str]) -> list[dict[str, Any]]:
    edges_payload: list[dict[str, Any]] = []
    if node_ids:
        edges = (
            (
                await db.execute(
                    select(KnowledgeGraphEdge).where(
                        KnowledgeGraphEdge.source_node_id.in_(node_ids),
                        KnowledgeGraphEdge.target_node_id.in_(node_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        edges_payload = [
            {
                "source": ref_by_id[edge.source_node_id],
                "target": ref_by_id[edge.target_node_id],
                "edge_type": edge.edge_type,
                "description": edge.description or "",
            }
            for edge in edges
            if edge.source_node_id in ref_by_id and edge.target_node_id in ref_by_id
        ]
    return edges_payload


def _node_payload(
    node: KnowledgeGraphNode,
    aliases_by_node: dict[str, list[str]],
    claims_by_node: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "node_type": node.node_type,
        "node_key": node.node_key,
        "display_name": node.display_name,
        "description": node.description or "",
        "classification": node.classification,
        "properties": dict(node.properties or {}),
        "aliases": sorted(set(aliases_by_node.get(node.id, []))),
        "claims": claims_by_node.get(node.id, []),
    }


async def export_entity_graph_package(
    db: AsyncSession,
    *,
    source_instance: str,
    project_id: str | None = None,
    node_types: list[str] | None = None,
    max_nodes: int = MAX_EXPORT_NODES,
) -> dict[str, Any]:
    """Build an unsigned portable package of the selected subgraph.

    ``project_id=None`` exports the instance-global scope (the hub's shared
    knowledge); a project id exports that project's graph.
    """
    max_nodes = max(1, min(int(max_nodes or MAX_EXPORT_NODES), MAX_EXPORT_NODES))
    nodes = await _selected_nodes(db, project_id, node_types, max_nodes)
    node_ids = [node.id for node in nodes]
    ref_by_id = {node.id: _node_ref(node.node_type, node.node_key) for node in nodes}

    aliases_by_node = await _aliases_by_node(db, node_ids)
    claims_by_node = await _claims_by_node(db, node_ids)
    edges_payload = await _edges_payload(db, node_ids, ref_by_id)
    nodes_payload = [_node_payload(node, aliases_by_node, claims_by_node) for node in nodes]

    return {
        "format": ENTITY_GRAPH_PACKAGE_FORMAT,
        "source_instance": str(source_instance or "unknown"),
        "generated_at": utc_now().isoformat(),
        "scope": {"project_id": project_id or None, "node_types": node_types or None},
        "counts": {"nodes": len(nodes_payload), "edges": len(edges_payload)},
        "nodes": nodes_payload,
        "edges": edges_payload,
    }
