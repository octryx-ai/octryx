"""Which spans of a revision still owe a graph episode."""

from __future__ import annotations

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import KnowledgeEvidenceSpan
from ....models.project.knowledge_temporal import KnowledgeGraphEpisode


def _has_episode(profile: str):
    return exists().where(
        and_(
            KnowledgeGraphEpisode.project_id == KnowledgeEvidenceSpan.project_id,
            KnowledgeGraphEpisode.revision_id == KnowledgeEvidenceSpan.revision_id,
            KnowledgeGraphEpisode.span_ordinal == KnowledgeEvidenceSpan.span_ordinal,
            KnowledgeGraphEpisode.extraction_profile == profile,
        )
    )


async def unextracted_spans(
    db: AsyncSession, project_id: str, revision_id: str, profile: str, *, limit: int
) -> tuple[KnowledgeEvidenceSpan, ...]:
    rows = await db.execute(
        select(KnowledgeEvidenceSpan)
        .where(
            KnowledgeEvidenceSpan.project_id == project_id,
            KnowledgeEvidenceSpan.revision_id == revision_id,
            ~_has_episode(profile),
        )
        .order_by(KnowledgeEvidenceSpan.span_ordinal)
        .limit(limit)
    )
    return tuple(rows.scalars().all())


__all__ = ["unextracted_spans"]
