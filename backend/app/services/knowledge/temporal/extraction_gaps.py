"""Which spans of a revision still owe a graph episode.

The episode ledger (``knowledge_graph_episodes``) is the record of what the graph holds. A span
owes extraction when it has no episode of the revision's current profile: never extracted, purged
by a profile migration (``profile_migration``), or extracted under the other profile. Reading this
instead of trusting an outbox cursor means an obligation that was recovered from dead letter, or
whose earlier spans a purge removed, still ends with every span extracted.
"""

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
    """The revision's first ``limit`` spans, in document order, without an episode of ``profile``."""
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
