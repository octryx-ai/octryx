"""Admin service for project access assignments."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import IdentityGroup, Role
from ...project.private_workspace import refuse_foreign_private
from ._admin_project_access_read import (
    PROJECT_NOT_FOUND,
    _get_project,
    _serialize_assignments,
    _serialize_group_assignments,
    _serialize_user_catalog,
)
from ._admin_project_access_roles import PROJECT_ROLE_ASSIGNMENTS_CONFIG_KEY, _serialize_role_assignments
from ._admin_project_access_write import (
    normalized_group_assignments,
    normalized_user_assignments,
    replace_group_rows,
    replace_user_rows,
    serialized_role_assignments_for,
)


async def require_administrable_project(db: AsyncSession, project_id: str, viewer_id: str) -> None:
    if await refuse_foreign_private(db, project_id, viewer_id):
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)


async def get_project_access(db: AsyncSession, *, project_id: str) -> dict[str, Any]:
    project = await _get_project(db, project_id)
    role_rows = (await db.execute(select(Role).order_by(Role.name.asc()))).scalars().all()
    group_rows = (await db.execute(select(IdentityGroup).order_by(IdentityGroup.name.asc()))).scalars().all()
    roles_by_id = {role.id: role.name for role in role_rows}
    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "is_active": bool(project.is_active),
        },
        "assignments": await _serialize_assignments(db, project_id),
        "group_assignments": await _serialize_group_assignments(db, project_id),
        "role_assignments": _serialize_role_assignments(project=project, roles_by_id=roles_by_id),
        "available_users": await _serialize_user_catalog(db),
        "available_roles": [
            {"id": role.id, "name": role.name, "description": role.description or ""} for role in role_rows
        ],
        "available_groups": [
            {
                "id": group.id,
                "name": group.name,
                "description": group.description or "",
                "is_active": bool(group.is_active),
            }
            for group in group_rows
        ],
        "group_assignments_supported": True,
        "rules": [
            "Direct user assignments are enforced by workspace visibility rules.",
            "Active group assignments grant project visibility to active group members.",
            "Direct and group-derived access are deduplicated at runtime; "
            "direct access remains visible as the primary source.",
        ],
    }


async def replace_project_access(
    db: AsyncSession,
    *,
    project_id: str,
    assignments: list[dict[str, Any]],
    group_assignments: list[dict[str, Any]] | None = None,
    role_assignments: list[dict[str, Any]] | None = None,
    granted_by_user_id: str,
) -> dict[str, Any]:
    project = await _get_project(db, project_id)
    normalized = await normalized_user_assignments(db, assignments)
    normalized_groups = await normalized_group_assignments(db, group_assignments)

    serialized_role_assignments: list[dict[str, Any]] | None = None
    if role_assignments is not None:
        serialized_role_assignments = await serialized_role_assignments_for(db, role_assignments)
    if role_assignments is not None:
        current_config = dict(project.config or {})
        current_config[PROJECT_ROLE_ASSIGNMENTS_CONFIG_KEY] = serialized_role_assignments or []
        project.config = current_config

    await replace_user_rows(
        db, project_id=project_id, normalized=normalized, granted_by_user_id=granted_by_user_id
    )
    await replace_group_rows(
        db, project_id=project_id, normalized_groups=normalized_groups, granted_by_user_id=granted_by_user_id
    )
    await db.commit()
    return await get_project_access(db, project_id=project_id)


async def replace_project_user_access(
    db: AsyncSession,
    *,
    project_id: str,
    assignments: list[dict[str, Any]],
    granted_by_user_id: str,
) -> dict[str, Any]:
    current = await get_project_access(db, project_id=project_id)
    return await replace_project_access(
        db,
        project_id=project_id,
        assignments=assignments,
        group_assignments=current["group_assignments"],
        granted_by_user_id=granted_by_user_id,
    )
