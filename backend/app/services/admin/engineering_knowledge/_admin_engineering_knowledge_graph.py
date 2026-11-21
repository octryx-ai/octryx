"""Knowledge-graph node/edge and review helpers for Engineering Knowledge admin services."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import AuditLog, EngineeringKnowledgeGraphNode
from ...engineering_knowledge import (
    inspect_engineering_knowledge_entity,
    serialize_graph_edge,
    serialize_graph_node,
    upsert_engineering_knowledge_edge,
    upsert_engineering_knowledge_node,
)
from ._admin_engineering_knowledge_common import (
    _optional_id,
    _pagination,
)
from ._admin_engineering_knowledge_graph_review import _apply_graph_review_action, _graph_node_filters
from ._admin_engineering_knowledge_serialization import as_dict


async def list_engineering_knowledge_graph_nodes(
    db: AsyncSession,
    *,
    query: str = "",
    node_type: str = "",
    status: str = "",
    trust_level: str = "",
    classification: str = "",
    scope_type: str = "",
    scope_id: str = "",
    repository_id: str = "",
    source: str = "",
    reviewer: str = "",
    validity: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    safe_limit, safe_offset = _pagination(limit, offset, max_limit=100)
    filters = _graph_node_filters(
        query=query,
        node_type=node_type,
        status=status,
        trust_level=trust_level,
        classification=classification,
        scope_type=scope_type,
        scope_id=scope_id,
        repository_id=repository_id,
        source=source,
        reviewer=reviewer,
        validity=validity,
    )
    stmt = select(EngineeringKnowledgeGraphNode).options(selectinload(EngineeringKnowledgeGraphNode.aliases))
    count_stmt = select(func.count()).select_from(EngineeringKnowledgeGraphNode)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    nodes = (
        (
            await db.execute(
                stmt.order_by(
                    EngineeringKnowledgeGraphNode.trust_level.asc(),
                    EngineeringKnowledgeGraphNode.updated_at.desc(),
                )
                .limit(safe_limit)
                .offset(safe_offset)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return {
        "items": [serialize_graph_node(node) for node in nodes],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "hasMore": safe_offset + len(nodes) < total,
        "stats": await _graph_review_stats(db),
    }


async def review_engineering_knowledge_graph_node(
    db: AsyncSession,
    *,
    node_id: str,
    admin_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    node = (
        await db.execute(
            select(EngineeringKnowledgeGraphNode)
            .options(selectinload(EngineeringKnowledgeGraphNode.aliases))
            .where(EngineeringKnowledgeGraphNode.id == node_id)
        )
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Engineering Knowledge Graph node not found")
    action = str(payload.get("action") or "").strip().lower()
    if action not in {
        "promote",
        "reject",
        "retract",
        "expire",
        "mark_non_shareable",
        "edit_metadata",
        "publish_candidate",
        "merge",
    }:
        raise HTTPException(status_code=422, detail="Unsupported Engineering Knowledge review action")

    previous = {
        "status": node.status,
        "trust_level": node.trust_level,
        "classification": node.classification,
        "valid_until": node.valid_until.isoformat() if node.valid_until else None,
    }
    _apply_graph_review_action(node, action=action, payload=payload, admin_id=admin_id)
    db.add(
        _graph_audit(
            admin_id,
            f"engineering_knowledge_graph.node_{action}",
            node.id,
            {"previous": previous, "current": serialize_graph_node(node), "reason": payload.get("reason") or ""},
        )
    )
    await db.commit()
    return await inspect_engineering_knowledge_entity(
        db,
        entity_ref=node.id,
        scope_type=node.scope_type,
        scope_id=node.scope_id,
        include_related=True,
    )


async def upsert_engineering_knowledge_graph_node(
    db: AsyncSession,
    *,
    admin_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    node = await upsert_engineering_knowledge_node(
        db,
        node_type=str(payload.get("node_type") or ""),
        node_key=str(payload.get("node_key") or ""),
        display_name=str(payload.get("display_name") or ""),
        summary=str(payload.get("summary") or ""),
        status=str(payload.get("status") or "active"),
        scope_type=str(payload.get("scope_type") or "global"),
        scope_id=_optional_id(payload.get("scope_id")),
        workspace_id=_optional_id(payload.get("workspace_id")),
        repository_id=_optional_id(payload.get("repository_id")),
        trust_level=str(payload.get("trust_level") or "bronze"),
        classification=str(payload.get("classification") or "internal"),
        properties=as_dict(payload.get("properties")),
        provenance=as_dict(payload.get("provenance")),
        source_refs=list(payload.get("source_refs") or []),
        aliases=list(payload.get("aliases") or []),
        created_by_user_id=admin_id,
    )
    db.add(_graph_audit(admin_id, "engineering_knowledge_graph.node_upserted", node.id, {"node_type": node.node_type}))
    await db.commit()
    return await inspect_engineering_knowledge_entity(
        db,
        entity_ref=node.id,
        scope_type=node.scope_type,
        scope_id=node.scope_id,
        include_related=True,
    )


async def upsert_engineering_knowledge_graph_edge(
    db: AsyncSession,
    *,
    admin_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    edge = await upsert_engineering_knowledge_edge(
        db,
        edge_type=str(payload.get("edge_type") or ""),
        source_node_id=str(payload.get("source_node_id") or ""),
        target_node_id=str(payload.get("target_node_id") or ""),
        status=str(payload.get("status") or "active"),
        scope_type=str(payload.get("scope_type") or "global"),
        scope_id=_optional_id(payload.get("scope_id")),
        trust_level=str(payload.get("trust_level") or "bronze"),
        classification=str(payload.get("classification") or "internal"),
        properties=as_dict(payload.get("properties")),
        provenance=as_dict(payload.get("provenance")),
        source_refs=list(payload.get("source_refs") or []),
        created_by_user_id=admin_id,
    )
    db.add(_graph_audit(admin_id, "engineering_knowledge_graph.edge_upserted", edge.id, {"edge_type": edge.edge_type}))
    await db.commit()
    return serialize_graph_edge(edge)


async def get_engineering_knowledge_graph_entity(
    db: AsyncSession,
    *,
    entity_ref: str,
    scope_type: str = "global",
    scope_id: str | None = None,
    include_related: bool = True,
) -> dict[str, Any]:
    return await inspect_engineering_knowledge_entity(
        db,
        entity_ref=entity_ref,
        scope_type=scope_type,
        scope_id=scope_id,
        include_related=include_related,
    )


def _graph_audit(admin_id: str, action: str, resource_id: str, details: dict[str, Any]) -> AuditLog:
    return AuditLog(
        user_id=admin_id,
        action=action,
        resource_type="engineering_knowledge_graph",
        resource_id=resource_id,
        details=details,
    )


async def _graph_review_stats(db: AsyncSession) -> dict[str, Any]:
    status_rows = (
        await db.execute(
            select(EngineeringKnowledgeGraphNode.status, func.count())
            .group_by(EngineeringKnowledgeGraphNode.status)
            .order_by(EngineeringKnowledgeGraphNode.status.asc())
        )
    ).all()
    trust_rows = (
        await db.execute(
            select(EngineeringKnowledgeGraphNode.trust_level, func.count())
            .group_by(EngineeringKnowledgeGraphNode.trust_level)
            .order_by(EngineeringKnowledgeGraphNode.trust_level.asc())
        )
    ).all()
    return {
        "status_counts": {str(status): int(count or 0) for status, count in status_rows},
        "trust_counts": {str(trust): int(count or 0) for trust, count in trust_rows},
    }


__all__ = [
    "_graph_audit",
    "_graph_review_stats",
    "get_engineering_knowledge_graph_entity",
    "list_engineering_knowledge_graph_nodes",
    "review_engineering_knowledge_graph_node",
    "upsert_engineering_knowledge_graph_edge",
    "upsert_engineering_knowledge_graph_node",
]
