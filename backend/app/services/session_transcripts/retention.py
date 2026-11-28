"""Stored transcripts live as long as their Workspace's ``retention_days`` (default 30), then they go."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, SessionTranscriptChunk
from ...time_utils import utc_now
from ..agent_gateway.transcript_policy_keys import transcript_policy_from_config
from .store import delete_chunk_object

logger = logging.getLogger(__name__)


async def purge_expired(db: AsyncSession) -> int:
    projects = (await db.execute(select(SessionTranscriptChunk.project_id).distinct())).scalars().all()
    deleted = 0
    now = utc_now()
    for project_id in projects:
        config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
        days = transcript_policy_from_config(config)[0].retention_days
        expired = (await db.execute(select(SessionTranscriptChunk).where(
            SessionTranscriptChunk.project_id == project_id,
            SessionTranscriptChunk.created_at < now - timedelta(days=days),
        ))).scalars().all()
        for chunk in expired:
            try:
                await delete_chunk_object(chunk)
            except Exception:  # noqa: BLE001 - the row stays for the next tick
                logger.warning("transcript object %s not deleted", chunk.id, exc_info=True)
                continue
            await db.delete(chunk)
            deleted += 1
    await db.commit()
    return deleted


__all__ = ["purge_expired"]
