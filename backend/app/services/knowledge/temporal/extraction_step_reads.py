"""The ledger reads of one ``extract_graph`` run (``extraction_step``)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.projection.outbox_lease import ClaimedProjection

from ....models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeSourceRevision
from ..ledger.errors import EvidenceRecordNotFoundError


async def _revision_of(db: AsyncSession, claim: ClaimedProjection):
    revision = (
        await db.execute(
            select(
                KnowledgeSourceRevision.state,
                KnowledgeSourceRevision.created_at,
                KnowledgeEvidenceSource.source_key,
                KnowledgeEvidenceSource.display_title,
            )
            .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
            .where(
                KnowledgeSourceRevision.id == claim.revision_id,
                KnowledgeSourceRevision.project_id == claim.project_id,
            )
        )
    ).first()
    if revision is None:
        raise EvidenceRecordNotFoundError()
    return revision
