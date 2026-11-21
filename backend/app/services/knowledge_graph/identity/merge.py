"""Applying a merge: re-point aliases, edges and claims, retire the merged node."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    KnowledgeClaim,
    KnowledgeGraphAlias,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeMergeProposal,
)
from ....time_utils import utc_now


async def _move_aliases(db: AsyncSession, keep: KnowledgeGraphNode, merge: KnowledgeGraphNode) -> int:
    moved = 0
    keep_aliases = {
        alias.normalized_alias
        for alias in (
            await db.execute(select(KnowledgeGraphAlias).where(KnowledgeGraphAlias.node_id == keep.id))
        ).scalars().all()
    }
    for alias in (
        await db.execute(select(KnowledgeGraphAlias).where(KnowledgeGraphAlias.node_id == merge.id))
    ).scalars().all():
        if alias.normalized_alias in keep_aliases:
            await db.delete(alias)
        else:
            alias.node_id = keep.id
            keep_aliases.add(alias.normalized_alias)
            moved += 1
    return moved


async def _move_edges(db: AsyncSession, keep: KnowledgeGraphNode, merge: KnowledgeGraphNode) -> int:
    moved = 0
    for edge in (
        await db.execute(
            select(KnowledgeGraphEdge).where(
                or_(
                    KnowledgeGraphEdge.source_node_id == merge.id,
                    KnowledgeGraphEdge.target_node_id == merge.id,
                )
            )
        )
    ).scalars().all():
        if edge.source_node_id == merge.id:
            edge.source_node_id = keep.id
        if edge.target_node_id == merge.id:
            edge.target_node_id = keep.id
        if edge.source_node_id == edge.target_node_id:
            await db.delete(edge)  # a self-loop created by the merge carries no information
        else:
            moved += 1
    return moved


async def _move_claims(db: AsyncSession, keep: KnowledgeGraphNode, merge: KnowledgeGraphNode) -> int:
    moved = 0
    for claim in (
        await db.execute(
            select(KnowledgeClaim).where(
                or_(
                    KnowledgeClaim.subject_node_id == merge.id,
                    KnowledgeClaim.object_node_id == merge.id,
                )
            )
        )
    ).scalars().all():
        if claim.subject_node_id == merge.id:
            claim.subject_node_id = keep.id
        if claim.object_node_id == merge.id:
            claim.object_node_id = keep.id
        moved += 1
    return moved


async def merge_nodes(db: AsyncSession, *, keep_node_id: str, merge_node_id: str) -> dict[str, Any]:
    """Apply a merge: re-point aliases, edges, and claims to the kept node,
    union properties/source_refs, and retire the merged node (status='merged')."""
    keep = await db.get(KnowledgeGraphNode, keep_node_id)
    merge = await db.get(KnowledgeGraphNode, merge_node_id)
    if keep is None or merge is None or keep.id == merge.id:
        raise ValueError("merge_nodes requires two distinct existing nodes")

    moved_aliases = await _move_aliases(db, keep, merge)
    moved_edges = await _move_edges(db, keep, merge)
    moved_claims = await _move_claims(db, keep, merge)

    keep.properties = {**(merge.properties or {}), **(keep.properties or {})}
    keep.source_refs = sorted({*(keep.source_refs or []), *(merge.source_refs or [])})
    if not keep.description and merge.description:
        keep.description = merge.description
    merge.status = "merged"
    merge.properties = {**(merge.properties or {}), "merged_into": keep.id}

    await db.flush()
    return {
        "kept": keep.id,
        "merged": merge.id,
        "moved_aliases": moved_aliases,
        "moved_edges": moved_edges,
        "moved_claims": moved_claims,
    }


async def decide_merge_proposal(
    db: AsyncSession,
    *,
    proposal_id: str,
    approve: bool,
    decided_by: str | None = None,
) -> dict[str, Any]:
    """Approve (apply) or reject a needs_review proposal — the governed gate."""
    proposal = await db.get(KnowledgeMergeProposal, proposal_id)
    if proposal is None:
        raise ValueError(f"Unknown merge proposal '{proposal_id}'")
    if proposal.status != "needs_review":
        return {"status": proposal.status, "proposal_id": proposal.id, "applied": False}

    proposal.decided_by = decided_by
    proposal.decided_at = utc_now()
    if not approve:
        proposal.status = "rejected"
        await db.flush()
        return {"status": "rejected", "proposal_id": proposal.id, "applied": False}

    result = await merge_nodes(db, keep_node_id=proposal.keep_node_id, merge_node_id=proposal.merge_node_id)
    proposal.status = "merged"
    await db.flush()
    return {"status": "merged", "proposal_id": proposal.id, "applied": True, **result}
