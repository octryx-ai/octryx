"""Whether a project may still be used by anything scoped to it.

A deleted or archived project is ``is_active = false`` (a soft delete). Resolution paths that act on
something scoped to a project (workflow definitions, Knowledge source connectors) ask this module
first and answer the explicit ``project_inactive`` state instead of using the scoped object.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_INACTIVE = "project_inactive"


async def project_is_inactive(db: AsyncSession, project_id: str | None) -> bool:
    """True only for an existing project that is soft-deleted or archived (``is_active`` false)."""
    # Local import: the state constant is read by models-free modules (execution_profile_service).
    from ..models import Project

    if not project_id:
        return False
    is_active = (await db.execute(select(Project.is_active).where(Project.id == project_id))).scalar_one_or_none()
    return is_active is False
