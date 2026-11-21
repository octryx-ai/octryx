"""Which episodes of a Workspace graph were extracted under which extraction profile (typing v2).

An episode records the profile it was extracted under. **Stale** means an episode whose profile is
not one of :data:`~.change_types.CURRENT_PROFILES`. A request to extract a product also owes every
current revision of the product that holds stale episodes (``extraction_requests``), so until its
own run completes, ``knowledge_changes`` says ``not_extracted`` for it.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_temporal import KnowledgeGraphEpisode
from .change_types import CURRENT_PROFILES


async def revisions_with_stale_episodes(db: AsyncSession, project_id: str, revision_ids: list[str]) -> set[str]:
    """Which of these revisions still hold episodes of a profile that is no longer current."""
    if not revision_ids:
        return set()
    rows = await db.execute(
        select(KnowledgeGraphEpisode.revision_id)
        .where(
            KnowledgeGraphEpisode.project_id == project_id,
            KnowledgeGraphEpisode.revision_id.in_(revision_ids),
            KnowledgeGraphEpisode.extraction_profile.not_in(sorted(CURRENT_PROFILES)),
        )
        .distinct()
    )
    return set(rows.scalars().all())


async def episodes_by_profile(db: AsyncSession, project_id: str) -> dict[str, int]:
    """The Workspace's episodes per extraction profile, so a profile migration can be watched."""
    rows = await db.execute(
        select(KnowledgeGraphEpisode.extraction_profile, func.count(KnowledgeGraphEpisode.episode_uuid))
        .where(KnowledgeGraphEpisode.project_id == project_id)
        .group_by(KnowledgeGraphEpisode.extraction_profile)
    )
    return {str(profile): int(count) for profile, count in rows.all()}


__all__ = [
    "episodes_by_profile",
    "revisions_with_stale_episodes",
]
