"""Aggregate counts and degree ranking for native code graph analytics."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphEdge, CodeGraphNode
from app.services.code_intelligence.graph_query_serializers import serialize_node
from app.services.code_intelligence.graph_query_support import load_nodes_by_ids


async def _count_by_node_field(db: AsyncSession, *, run_id: str, field: Any) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(field, func.count())
            .where(CodeGraphNode.run_id == run_id, CodeGraphNode.is_current.is_(True))
            .group_by(field)
            .order_by(func.count().desc(), field.asc())
        )
    ).all()
    return [{"value": str(value or "unknown"), "count": int(count or 0)} for value, count in rows]


async def _count_by_edge_field(db: AsyncSession, *, run_id: str, field: Any) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(field, func.count())
            .where(CodeGraphEdge.run_id == run_id, CodeGraphEdge.is_current.is_(True))
            .group_by(field)
            .order_by(func.count().desc(), field.asc())
        )
    ).all()
    return [{"value": str(value or "unknown"), "count": int(count or 0)} for value, count in rows]


async def _rank_nodes_by_degree(
    db: AsyncSession,
    *,
    run_id: str,
    relation: str | None = None,
    node_type: str | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    in_degree = await _degree_counts(db, run_id=run_id, column=CodeGraphEdge.target_node_id, relation=relation)
    out_degree = await _degree_counts(db, run_id=run_id, column=CodeGraphEdge.source_node_id, relation=relation)
    node_ids = set(in_degree) | set(out_degree)
    nodes = await load_nodes_by_ids(db, run_id=run_id, node_ids=node_ids)
    if node_type:
        nodes = [node for node in nodes if node.node_type == node_type]
    ranked = []
    for node in nodes:
        incoming = in_degree.get(node.id, 0)
        outgoing = out_degree.get(node.id, 0)
        ranked.append(
            {
                "node": serialize_node(node),
                "degree": incoming + outgoing,
                "incoming_degree": incoming,
                "outgoing_degree": outgoing,
            }
        )
    return sorted(
        ranked,
        key=lambda item: (
            -int(item["degree"]),
            -int(item["incoming_degree"]),
            item["node"].get("path") or "",
            item["node"].get("name") or "",
        ),
    )[:limit]


async def _degree_counts(db: AsyncSession, *, run_id: str, column: Any, relation: str | None) -> dict[str, int]:
    stmt = (
        select(column, func.count())
        .where(CodeGraphEdge.run_id == run_id, CodeGraphEdge.is_current.is_(True))
        .group_by(column)
    )
    if relation:
        stmt = stmt.where(CodeGraphEdge.relation == relation)
    rows = (await db.execute(stmt)).all()
    return {str(node_id): int(count or 0) for node_id, count in rows if node_id}
