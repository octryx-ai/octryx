"""The detail payload of one entity node: aliases, claims and relations."""

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


async def _aliases_and_claims(db: AsyncSession, node_id: str) -> tuple[list[Any], list[Any]]:
    aliases = (
        (
            await db.execute(
                select(KnowledgeGraphAlias.alias_value).where(KnowledgeGraphAlias.node_id == node_id)
            )
        )
        .scalars()
        .all()
    )
    claims = (
        (
            await db.execute(
                select(KnowledgeClaim)
                .where(KnowledgeClaim.subject_node_id == node_id, KnowledgeClaim.status == "active")
                .order_by(KnowledgeClaim.created_at.desc())
                .limit(40)
            )
        )
        .scalars()
        .all()
    )
    return aliases, claims


async def _relations(db: AsyncSession, node_id: str) -> list[dict[str, Any]]:
    edges = (
        (
            await db.execute(
                select(KnowledgeGraphEdge)
                .where(
                    (KnowledgeGraphEdge.source_node_id == node_id)
                    | (KnowledgeGraphEdge.target_node_id == node_id)
                )
                .limit(120)
            )
        )
        .scalars()
        .all()
    )
    peer_ids = {edge.source_node_id for edge in edges} | {edge.target_node_id for edge in edges}
    peer_ids.discard(node_id)
    peers = {
        peer.id: peer
        for peer in (
            (await db.execute(select(KnowledgeGraphNode).where(KnowledgeGraphNode.id.in_(peer_ids))))
            .scalars()
            .all()
        )
    }
    relations = []
    for edge in edges:
        outgoing = edge.source_node_id == node_id
        peer = peers.get(edge.target_node_id if outgoing else edge.source_node_id)
        if peer is None:
            continue
        relations.append(
            {
                "edge_type": edge.edge_type,
                "direction": "out" if outgoing else "in",
                "peer_id": peer.id,
                "peer_name": peer.display_name,
                "peer_type": peer.node_type,
                "description": (edge.description or "")[:200],
            }
        )
    return relations


async def get_entity_node_detail(db: AsyncSession, *, node_id: str) -> dict[str, Any] | None:
    node = await db.get(KnowledgeGraphNode, node_id)
    if node is None:
        return None
    aliases, claims = await _aliases_and_claims(db, node_id)
    relations = await _relations(db, node_id)
    return {
        "id": node.id,
        "node_type": node.node_type,
        "display_name": node.display_name,
        "description": node.description or "",
        "trust_level": node.trust_level,
        "status": node.status,
        "properties": dict(node.properties or {}),
        "source_refs": list(node.source_refs or []),
        "aliases": sorted({str(alias) for alias in aliases}),
        "claims": [
            {
                "claim_type": claim.claim_type,
                "statement": claim.statement,
                "valid_from_label": claim.valid_from_label,
                "valid_until_label": claim.valid_until_label,
            }
            for claim in claims
        ],
        "relations": relations,
    }
