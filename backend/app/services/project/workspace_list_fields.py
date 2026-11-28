"""The workspace list's summary fields: active member count and last update (Admin › Workspaces)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, ProjectGroup, User, UserGroup, UserProject
from ...time_utils import ensure_utc


async def workspace_list_fields(db: AsyncSession, project_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    ids = sorted({str(project_id) for project_id in project_ids if project_id})
    if not ids:
        return {}
    members = union(
        select(UserProject.project_id.label("project_id"), UserProject.user_id.label("user_id"))
        .where(UserProject.project_id.in_(ids)),
        select(ProjectGroup.project_id.label("project_id"), UserGroup.user_id.label("user_id"))
        .join(UserGroup, UserGroup.group_id == ProjectGroup.group_id).where(ProjectGroup.project_id.in_(ids)),
    ).subquery()
    counts = dict((await db.execute(
        select(members.c.project_id, func.count(func.distinct(members.c.user_id)))
        .join(User, User.id == members.c.user_id).where(User.is_active.is_(True))
        .group_by(members.c.project_id)
    )).all())
    updated = dict((await db.execute(select(Project.id, Project.updated_at).where(Project.id.in_(ids)))).all())
    return {
        project_id: {
            "member_count": int(counts.get(project_id, 0)),
            "updated_at": ensure_utc(updated[project_id]).isoformat() if updated.get(project_id) else None,
            "class": None,
        }
        for project_id in ids
    }


__all__ = ["workspace_list_fields"]
