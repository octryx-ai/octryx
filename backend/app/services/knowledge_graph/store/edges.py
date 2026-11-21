"""Relation edges between graph nodes and neighbourhood lookups."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import KnowledgeGraphEdge, KnowledgeGraphNode
from ...knowledge_trust import evidence_trust_level
from .aliases import _project_filter
from .descriptions import _embed_text_for, merge_descriptions


async def upsert_edge(
    db: AsyncSession,
    *,
    project_id: str | None,
    edge_type: str,
    source_node_id: str,
    target_node_id: str,
    description: str = "",
    keywords: list[str] | None = None,
    weight: float = 1.0,
    source_refs: list[str] | None = None,
    embed: bool = True,
    trust_level: str | None = None,
) -> KnowledgeGraphEdge:
    """``trust_level`` pins an explicit level (e.g. "federated"); when omitted
    the level is evidence-based — multi-source confirmation promotes to silver."""
    edge = (
        await db.execute(
            select(KnowledgeGraphEdge).where(
                _project_filter(KnowledgeGraphEdge.project_id, project_id),
                KnowledgeGraphEdge.edge_type == edge_type,
                KnowledgeGraphEdge.source_node_id == source_node_id,
                KnowledgeGraphEdge.target_node_id == target_node_id,
            )
        )
    ).scalars().first()
    if edge is None:
        edge = KnowledgeGraphEdge(
            id=str(uuid.uuid4()),
            project_id=project_id,
            edge_type=edge_type,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            description=description or "",
            keywords=list(keywords or []),
            weight=weight,
            source_refs=list(source_refs or []),
        )
        db.add(edge)
    else:
        if description:
            edge.description = merge_descriptions(edge.description or "", description)
        if keywords:
            edge.keywords = sorted({*(edge.keywords or []), *keywords})
        edge.weight = weight
        if source_refs:
            edge.source_refs = sorted({*(edge.source_refs or []), *source_refs})
    edge.trust_level = trust_level or evidence_trust_level(edge.trust_level, edge.source_refs)
    await db.flush()
    if embed and edge.description:
        vector = await _embed_text_for(db, edge.description)
        if vector is not None:
            for key, value in vector.items():
                setattr(edge, key, value)
    await db.flush()
    return edge


def _neighbor_entry(edge: KnowledgeGraphEdge, node_id: str, other: KnowledgeGraphNode | None) -> dict[str, Any]:
    return {
        "edge_type": edge.edge_type,
        "direction": "out" if edge.source_node_id == node_id else "in",
        "description": edge.description,
        "trust_level": edge.trust_level,
        "evidence_count": len(edge.source_refs or []),
        "node": None
        if other is None
        else {
            "id": other.id,
            "node_type": other.node_type,
            "display_name": other.display_name,
            "trust_level": other.trust_level,
        },
    }


async def get_neighbors(db: AsyncSession, *, node_id: str, limit: int = 25) -> list[dict[str, Any]]:
    edges = (
        (
            await db.execute(
                select(KnowledgeGraphEdge)
                .where(
                    or_(
                        KnowledgeGraphEdge.source_node_id == node_id,
                        KnowledgeGraphEdge.target_node_id == node_id,
                    )
                )
                .limit(max(1, min(int(limit or 25), 200)))
            )
        )
        .scalars()
        .all()
    )
    neighbors: list[dict[str, Any]] = []
    for edge in edges:
        other_id = edge.target_node_id if edge.source_node_id == node_id else edge.source_node_id
        other = await db.get(KnowledgeGraphNode, other_id)
        neighbors.append(_neighbor_entry(edge, node_id, other))
    return neighbors
