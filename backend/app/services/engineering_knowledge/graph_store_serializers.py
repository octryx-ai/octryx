"""Serializers that turn Engineering Knowledge Graph rows into plain dictionaries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    EngineeringKnowledgeGraphAlias,
    EngineeringKnowledgeGraphEdge,
    EngineeringKnowledgeGraphNode,
)
from .graph_store_rules import _as_dict, _as_list, _iso


def serialize_graph_node(node: EngineeringKnowledgeGraphNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "node_type": node.node_type,
        "node_key": node.node_key,
        "display_name": node.display_name,
        "summary": node.summary or "",
        "status": node.status,
        "scope_type": node.scope_type,
        "scope_id": node.scope_id,
        "scope_key": node.scope_key,
        "workspace_id": node.workspace_id,
        "repository_id": node.repository_id,
        "trust_level": node.trust_level,
        "classification": node.classification,
        "valid_from": _iso(node.valid_from),
        "valid_until": _iso(node.valid_until),
        "properties": _as_dict(node.properties_json),
        "provenance": _as_dict(node.provenance_json),
        "source_refs": _as_list(node.source_refs_json),
        "aliases": [serialize_graph_alias(alias) for alias in list(node.aliases or [])],
        "created_by_user_id": node.created_by_user_id,
        "created_at": _iso(node.created_at),
        "updated_at": _iso(node.updated_at),
    }


def serialize_graph_alias(alias: EngineeringKnowledgeGraphAlias) -> dict[str, Any]:
    return {
        "id": alias.id,
        "node_id": alias.node_id,
        "alias_type": alias.alias_type,
        "alias_value": alias.alias_value,
        "normalized_alias": alias.normalized_alias,
        "scope_key": alias.scope_key,
        "provenance": _as_dict(alias.provenance_json),
        "source_refs": _as_list(alias.source_refs_json),
    }


def serialize_graph_edge(edge: EngineeringKnowledgeGraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "edge_type": edge.edge_type,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "status": edge.status,
        "scope_type": edge.scope_type,
        "scope_id": edge.scope_id,
        "scope_key": edge.scope_key,
        "trust_level": edge.trust_level,
        "classification": edge.classification,
        "valid_from": _iso(edge.valid_from),
        "valid_until": _iso(edge.valid_until),
        "properties": _as_dict(edge.properties_json),
        "provenance": _as_dict(edge.provenance_json),
        "source_refs": _as_list(edge.source_refs_json),
        "created_by_user_id": edge.created_by_user_id,
        "created_at": _iso(edge.created_at),
        "updated_at": _iso(edge.updated_at),
    }


async def _serialize_entity(
    db: AsyncSession,
    *,
    node: EngineeringKnowledgeGraphNode,
    include_related: bool,
) -> dict[str, Any]:
    await db.refresh(node, attribute_names=["aliases"])
    payload = serialize_graph_node(node)
    if not include_related:
        return payload
    edge_rows = (
        await db.execute(
            select(EngineeringKnowledgeGraphEdge)
            .options(
                selectinload(EngineeringKnowledgeGraphEdge.source_node).selectinload(
                    EngineeringKnowledgeGraphNode.aliases
                ),
                selectinload(EngineeringKnowledgeGraphEdge.target_node).selectinload(
                    EngineeringKnowledgeGraphNode.aliases
                ),
            )
            .where(
                EngineeringKnowledgeGraphEdge.scope_key == node.scope_key,
                or_(
                    EngineeringKnowledgeGraphEdge.source_node_id == node.id,
                    EngineeringKnowledgeGraphEdge.target_node_id == node.id,
                ),
            )
            .order_by(EngineeringKnowledgeGraphEdge.edge_type.asc(), EngineeringKnowledgeGraphEdge.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    payload["related_edges"] = [_serialize_related_edge(edge, node_id=node.id) for edge in edge_rows]
    return payload


def _serialize_related_edge(edge: EngineeringKnowledgeGraphEdge, *, node_id: str) -> dict[str, Any]:
    payload = serialize_graph_edge(edge)
    other = edge.target_node if edge.source_node_id == node_id else edge.source_node
    direction = "outgoing" if edge.source_node_id == node_id else "incoming"
    payload["direction"] = direction
    payload["related_node"] = serialize_graph_node(other) if other else None
    return payload
