"""Storage helpers for the Engineering Knowledge Graph."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import EngineeringKnowledgeGraphAlias, EngineeringKnowledgeGraphNode
from .graph_store_rules import _normalize_alias, _normalize_key, _normalize_type, _scope
from .graph_store_serializers import _serialize_entity

__all__ = ["inspect_engineering_knowledge_entity", "resolve_engineering_knowledge_alias"]


async def resolve_engineering_knowledge_alias(
    db: AsyncSession,
    *,
    alias: str,
    alias_type: str = "",
    scope_type: str = "global",
    scope_id: str | None = None,
) -> EngineeringKnowledgeGraphNode | None:
    safe_scope = _scope(scope_type=scope_type, scope_id=scope_id)
    normalized = _normalize_alias(alias)
    if not normalized:
        return None
    stmt = (
        select(EngineeringKnowledgeGraphAlias)
        .options(selectinload(EngineeringKnowledgeGraphAlias.node))
        .where(
            EngineeringKnowledgeGraphAlias.scope_key == safe_scope["scope_key"],
            EngineeringKnowledgeGraphAlias.normalized_alias == normalized,
        )
    )
    if alias_type:
        stmt = stmt.where(EngineeringKnowledgeGraphAlias.alias_type == _normalize_type(alias_type, label="alias_type"))
    row = (await db.execute(stmt)).scalar_one_or_none()
    return row.node if row else None


async def inspect_engineering_knowledge_entity(
    db: AsyncSession,
    *,
    entity_ref: str,
    scope_type: str = "global",
    scope_id: str | None = None,
    include_related: bool = True,
) -> dict[str, Any]:
    safe_scope = _scope(scope_type=scope_type, scope_id=scope_id)
    node = await _get_node_by_ref(db, entity_ref=entity_ref, scope_key=safe_scope["scope_key"])
    if node is None:
        raise HTTPException(status_code=404, detail="Engineering Knowledge Graph entity not found")
    return await _serialize_entity(db, node=node, include_related=include_related)


async def _get_node_by_ref(
    db: AsyncSession,
    *,
    entity_ref: str,
    scope_key: str,
) -> EngineeringKnowledgeGraphNode | None:
    direct = (
        await db.execute(
            select(EngineeringKnowledgeGraphNode)
            .options(selectinload(EngineeringKnowledgeGraphNode.aliases))
            .where(
                EngineeringKnowledgeGraphNode.scope_key == scope_key,
                or_(
                    EngineeringKnowledgeGraphNode.id == entity_ref,
                    EngineeringKnowledgeGraphNode.node_key == _normalize_key(entity_ref, label="entity_ref"),
                ),
            )
        )
    ).scalar_one_or_none()
    if direct is not None:
        return direct
    scope_type, scope_id = scope_key.split(":", 1)
    return await resolve_engineering_knowledge_alias(db, alias=entity_ref, scope_type=scope_type, scope_id=scope_id)
