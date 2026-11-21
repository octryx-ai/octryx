"""Scoped totals, degrees, neighbourhoods and payload shapes of the entity graph."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_graph import (
    KnowledgeClaim,
    KnowledgeCommunity,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
)


def _node_payload(node: KnowledgeGraphNode, degree: int, *, matched: bool = False) -> dict[str, Any]:
    return {
        "id": node.id,
        "node_type": node.node_type,
        "display_name": node.display_name,
        "description": (node.description or "")[:400],
        "degree": degree,
        "trust_level": node.trust_level,
        "matched": matched,
    }


def _in_scope(column, project_id: str):
    """The project's own rows plus the instance-global layer."""
    return (column == project_id) | (column.is_(None))


async def _scoped_totals(db: AsyncSession, project_id: str) -> dict[str, int]:
    """Totals of the shown scope: one project (plus global rows) or, without a project, the instance."""
    totals: dict[str, int] = {}
    for key, model, active_only in (
        ("total_nodes", KnowledgeGraphNode, True),
        ("total_edges", KnowledgeGraphEdge, False),
        ("total_claims", KnowledgeClaim, True),
        ("total_communities", KnowledgeCommunity, True),
    ):
        stmt = select(func.count()).select_from(model)
        if active_only:
            stmt = stmt.where(model.status == "active")
        if project_id:
            stmt = stmt.where(_in_scope(model.project_id, project_id))
        totals[key] = int((await db.execute(stmt)).scalar_one())
    return totals


def _edge_payload(edge: KnowledgeGraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source": edge.source_node_id,
        "target": edge.target_node_id,
        "edge_type": edge.edge_type,
        "trust_level": edge.trust_level,
        "description": (edge.description or "")[:200],
    }


async def _degrees(db: AsyncSession, node_ids: list[str]) -> dict[str, int]:
    if not node_ids:
        return {}
    degrees: dict[str, int] = defaultdict(int)
    for column in (KnowledgeGraphEdge.source_node_id, KnowledgeGraphEdge.target_node_id):
        rows = await db.execute(
            select(column, func.count()).where(column.in_(node_ids)).group_by(column)
        )
        for node_id, count in rows.all():
            degrees[node_id] += int(count)
    return dict(degrees)


async def _edges_between(db: AsyncSession, node_ids: set[str]) -> list[KnowledgeGraphEdge]:
    if not node_ids:
        return []
    return list(
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


async def _neighbor_ids(db: AsyncSession, node_ids: set[str], *, limit: int) -> set[str]:
    if not node_ids or limit <= 0:
        return set()
    rows = (
        (
            await db.execute(
                select(KnowledgeGraphEdge.source_node_id, KnowledgeGraphEdge.target_node_id)
                .where(
                    (KnowledgeGraphEdge.source_node_id.in_(node_ids))
                    | (KnowledgeGraphEdge.target_node_id.in_(node_ids))
                )
                .limit(limit * 4)
            )
        ).all()
    )
    found: set[str] = set()
    for source_id, target_id in rows:
        found.add(source_id)
        found.add(target_id)
        if len(found) >= limit + len(node_ids):
            break
    return found - node_ids
