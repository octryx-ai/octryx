"""Claims (versioned facts) attached to graph nodes."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import KnowledgeClaim


async def add_claim(
    db: AsyncSession,
    *,
    project_id: str | None,
    subject_node_id: str,
    statement: str,
    claim_type: str = "fact",
    object_node_id: str | None = None,
    valid_from_label: str | None = None,
    valid_until_label: str | None = None,
    source_refs: list[str] | None = None,
) -> KnowledgeClaim:
    claim = KnowledgeClaim(
        id=str(uuid.uuid4()),
        project_id=project_id,
        subject_node_id=subject_node_id,
        object_node_id=object_node_id,
        claim_type=claim_type,
        statement=statement,
        valid_from_label=valid_from_label,
        valid_until_label=valid_until_label,
        source_refs=list(source_refs or []),
    )
    db.add(claim)
    await db.flush()
    return claim


async def replace_claims_of_type(
    db: AsyncSession,
    *,
    project_id: str | None,
    subject_node_id: str,
    claim_type: str,
    claims: list[dict[str, Any]],
) -> int:
    """Replace ALL claims of one type on a node with a fresh set.

    For state-of-the-world claim types that a re-scan supersedes (code index
    stats, CI pipeline stages, container build info) — accumulating them would
    surface stale facts next to current ones.
    """
    existing_ids = (
        (
            await db.execute(
                select(KnowledgeClaim.id).where(
                    KnowledgeClaim.subject_node_id == subject_node_id,
                    KnowledgeClaim.claim_type == claim_type,
                )
            )
        )
        .scalars()
        .all()
    )
    if existing_ids:
        await db.execute(sa_delete(KnowledgeClaim).where(KnowledgeClaim.id.in_(existing_ids)))
    created = 0
    for claim in claims:
        statement = str(claim.get("statement") or "").strip()
        if not statement:
            continue
        await add_claim(
            db,
            project_id=project_id,
            subject_node_id=subject_node_id,
            statement=statement,
            claim_type=claim_type,
            valid_from_label=claim.get("valid_from_label"),
            source_refs=list(claim.get("source_refs") or []),
        )
        created += 1
    return created


async def get_claims_for_node(db: AsyncSession, *, node_id: str) -> list[KnowledgeClaim]:
    return list(
        (
            await db.execute(
                select(KnowledgeClaim).where(
                    and_(
                        KnowledgeClaim.subject_node_id == node_id,
                        KnowledgeClaim.status == "active",
                    )
                )
            )
        )
        .scalars()
        .all()
    )
