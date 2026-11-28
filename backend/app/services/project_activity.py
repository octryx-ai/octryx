"""Whether a project may still be used by anything scoped to it. An inactive project answers ``project_inactive``
instead of using the scoped object."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_INACTIVE = "project_inactive"


async def project_is_inactive(db: AsyncSession, project_id: str | None) -> bool:
    # Local import: the state constant is read by models-free modules (execution_profile_service).
    from ..models import Project

    if not project_id:
        return False
    is_active = (await db.execute(select(Project.is_active).where(Project.id == project_id))).scalar_one_or_none()
    return is_active is False
