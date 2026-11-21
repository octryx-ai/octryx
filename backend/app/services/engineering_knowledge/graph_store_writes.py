"""Insert-or-update writes for Engineering Knowledge Graph nodes, edges and aliases."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgeGraphAlias,
    EngineeringKnowledgeGraphEdge,
    EngineeringKnowledgeGraphNode,
)
from .graph_store_rules import (
    CLASSIFICATIONS,
    EDGE_TYPES,
    NODE_TYPES,
    STATUSES,
    TRUST_LEVELS,
    _normalize_alias,
    _normalize_enum,
    _normalize_key,
    _normalize_type,
    _safe_dict,
    _safe_refs,
    _scope,
)


async def upsert_engineering_knowledge_node(
    db: AsyncSession,
    *,
    node_type: str,
    node_key: str,
    display_name: str = "",
    summary: str = "",
    status: str = "active",
    scope_type: str = "global",
    scope_id: str | None = None,
    workspace_id: str | None = None,
    repository_id: str | None = None,
    trust_level: str = "bronze",
    classification: str = "internal",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    properties: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    aliases: list[dict[str, Any]] | None = None,
    created_by_user_id: str | None = None,
) -> EngineeringKnowledgeGraphNode:
    safe_node_type = _normalize_type(node_type, allowed=NODE_TYPES, label="node_type")
    safe_node_key = _normalize_key(node_key, label="node_key")
    safe_scope = _scope(
        scope_type=scope_type,
        scope_id=scope_id,
        workspace_id=workspace_id,
        repository_id=repository_id,
    )
    fields = _safe_common_fields(
        status=status,
        trust_level=trust_level,
        classification=classification,
        properties=properties,
        provenance=provenance,
        source_refs=source_refs,
    )
    node = await _find_node(db, scope_key=safe_scope["scope_key"], node_type=safe_node_type, node_key=safe_node_key)
    if node is None:
        node = EngineeringKnowledgeGraphNode(
            node_type=safe_node_type,
            node_key=safe_node_key,
            scope_type=safe_scope["scope_type"],
            scope_id=safe_scope["scope_id"],
            scope_key=safe_scope["scope_key"],
            workspace_id=workspace_id,
            repository_id=repository_id,
            created_by_user_id=created_by_user_id,
        )
        db.add(node)

    node.display_name = display_name.strip() or node.display_name or safe_node_key
    node.summary = summary.strip()
    _apply_common_fields(node, fields, valid_from=valid_from, valid_until=valid_until)
    await db.flush()
    await _upsert_aliases(db, node=node, aliases=aliases or [], default_source_refs=fields["source_refs_json"])
    await db.flush()
    return node


async def upsert_engineering_knowledge_edge(
    db: AsyncSession,
    *,
    edge_type: str,
    source_node_id: str,
    target_node_id: str,
    status: str = "active",
    scope_type: str = "global",
    scope_id: str | None = None,
    trust_level: str = "bronze",
    classification: str = "internal",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    properties: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    created_by_user_id: str | None = None,
) -> EngineeringKnowledgeGraphEdge:
    safe_edge_type = _normalize_type(edge_type, allowed=EDGE_TYPES, label="edge_type")
    safe_scope = _scope(scope_type=scope_type, scope_id=scope_id)
    source = await db.get(EngineeringKnowledgeGraphNode, source_node_id)
    target = await db.get(EngineeringKnowledgeGraphNode, target_node_id)
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="Engineering Knowledge Graph node not found")
    fields = _safe_common_fields(
        status=status,
        trust_level=trust_level,
        classification=classification,
        properties=properties,
        provenance=provenance,
        source_refs=source_refs,
    )
    edge = (
        await db.execute(
            select(EngineeringKnowledgeGraphEdge).where(
                EngineeringKnowledgeGraphEdge.scope_key == safe_scope["scope_key"],
                EngineeringKnowledgeGraphEdge.edge_type == safe_edge_type,
                EngineeringKnowledgeGraphEdge.source_node_id == source.id,
                EngineeringKnowledgeGraphEdge.target_node_id == target.id,
            )
        )
    ).scalar_one_or_none()
    if edge is None:
        edge = EngineeringKnowledgeGraphEdge(
            edge_type=safe_edge_type,
            source_node_id=source.id,
            target_node_id=target.id,
            scope_type=safe_scope["scope_type"],
            scope_id=safe_scope["scope_id"],
            scope_key=safe_scope["scope_key"],
            created_by_user_id=created_by_user_id,
        )
        db.add(edge)
    _apply_common_fields(edge, fields, valid_from=valid_from, valid_until=valid_until)
    await db.flush()
    return edge


async def _find_node(
    db: AsyncSession,
    *,
    scope_key: str | None,
    node_type: str,
    node_key: str,
) -> EngineeringKnowledgeGraphNode | None:
    return (
        await db.execute(
            select(EngineeringKnowledgeGraphNode).where(
                EngineeringKnowledgeGraphNode.scope_key == scope_key,
                EngineeringKnowledgeGraphNode.node_type == node_type,
                EngineeringKnowledgeGraphNode.node_key == node_key,
            )
        )
    ).scalar_one_or_none()


def _safe_common_fields(
    *,
    status: str,
    trust_level: str,
    classification: str,
    properties: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
    source_refs: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    # Validation runs in this order so the first invalid field decides which 400 the caller sees.
    return {
        "status": _normalize_enum(status, allowed=STATUSES, label="status"),
        "trust_level": _normalize_enum(trust_level, allowed=TRUST_LEVELS, label="trust_level"),
        "classification": _normalize_enum(classification, allowed=CLASSIFICATIONS, label="classification"),
        "properties_json": _safe_dict(properties, label="properties"),
        "provenance_json": _safe_dict(provenance, label="provenance"),
        "source_refs_json": _safe_refs(source_refs, label="source_refs"),
    }


def _apply_common_fields(
    row: EngineeringKnowledgeGraphNode | EngineeringKnowledgeGraphEdge,
    fields: dict[str, Any],
    *,
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> None:
    row.status = fields["status"]
    row.trust_level = fields["trust_level"]
    row.classification = fields["classification"]
    row.valid_from = valid_from
    row.valid_until = valid_until
    row.properties_json = fields["properties_json"]
    row.provenance_json = fields["provenance_json"]
    row.source_refs_json = fields["source_refs_json"]


async def _upsert_aliases(
    db: AsyncSession,
    *,
    node: EngineeringKnowledgeGraphNode,
    aliases: list[dict[str, Any]],
    default_source_refs: list[dict[str, Any]],
) -> None:
    for alias in aliases:
        if not isinstance(alias, dict):
            continue
        alias_value = str(alias.get("value") or alias.get("alias_value") or "").strip()
        if not alias_value:
            continue
        alias_type = _normalize_type(alias.get("type") or alias.get("alias_type") or "name", label="alias_type")
        normalized_alias = _normalize_alias(alias_value)
        provenance = _safe_dict(alias.get("provenance"), label="alias.provenance")
        source_refs = _safe_refs(alias.get("source_refs") or default_source_refs, label="alias.source_refs")
        existing = (
            await db.execute(
                select(EngineeringKnowledgeGraphAlias).where(
                    EngineeringKnowledgeGraphAlias.scope_key == node.scope_key,
                    EngineeringKnowledgeGraphAlias.alias_type == alias_type,
                    EngineeringKnowledgeGraphAlias.normalized_alias == normalized_alias,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                EngineeringKnowledgeGraphAlias(
                    node_id=node.id,
                    alias_type=alias_type,
                    alias_value=alias_value,
                    normalized_alias=normalized_alias,
                    scope_key=node.scope_key,
                    provenance_json=provenance,
                    source_refs_json=source_refs,
                )
            )
        else:
            existing.node_id = node.id
            existing.alias_value = alias_value
            existing.provenance_json = provenance
            existing.source_refs_json = source_refs

