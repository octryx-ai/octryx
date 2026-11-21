"""Write side of project access: request validation and the replacement of assignment rows."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    IdentityGroup,
    ProjectGroup,
    ProjectGroupRoleAssignment,
    ProjectUserRoleAssignment,
    Role,
    User,
    UserProject,
)
from ._admin_project_access_roles import (
    DEFAULT_PROJECT_ACCESS_ROLE,
    _merge_project_roles,
    _normalize_global_role_name,
    _normalize_project_roles,
    _normalize_role_identifier,
)


async def normalized_user_assignments(db: AsyncSession, assignments: list[dict[str, Any]]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for item in assignments:
        user_id = str(item.get("user_id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=400, detail="Assignment user_id is required")
        normalized[user_id] = _normalize_project_roles(
            item.get("project_roles") or item.get("project_role") or item.get("role")
        )
    if normalized:
        users = (await db.execute(select(User.id).where(User.id.in_(normalized)))).scalars().all()
        missing = sorted(set(normalized) - set(users))
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown user(s): {', '.join(missing)}")
    return normalized


async def normalized_group_assignments(
    db: AsyncSession, group_assignments: list[dict[str, Any]] | None
) -> dict[str, list[str]]:
    normalized_groups: dict[str, list[str]] = {}
    for item in group_assignments or []:
        group_id = str(item.get("group_id") or "").strip()
        if not group_id:
            raise HTTPException(status_code=400, detail="Group assignment group_id is required")
        normalized_groups[group_id] = _normalize_project_roles(
            item.get("project_roles") or item.get("project_role") or item.get("role")
        )
    if normalized_groups:
        groups = (
            await db.execute(select(IdentityGroup.id).where(IdentityGroup.id.in_(normalized_groups)))
        ).scalars().all()
        missing_groups = sorted(set(normalized_groups) - set(groups))
        if missing_groups:
            raise HTTPException(status_code=400, detail=f"Unknown group(s): {', '.join(missing_groups)}")
    return normalized_groups


async def _matching_roles(db: AsyncSession, role_assignments: list[dict[str, Any]]) -> list[Any]:
    role_filters = []
    role_names = {_normalize_global_role_name(item.get("role")) for item in role_assignments if item.get("role")}
    role_ids = {_normalize_role_identifier(item.get("role_id")) for item in role_assignments if item.get("role_id")}
    if role_ids:
        role_filters.append(Role.id.in_(sorted(role_ids)))
    if role_names:
        role_filters.append(func.lower(Role.name).in_(sorted(role_names)))
    matching_roles = []
    if role_filters:
        matching_roles = (await db.execute(select(Role.id, Role.name).where(or_(*role_filters)))).all()
    return matching_roles


async def serialized_role_assignments_for(
    db: AsyncSession, role_assignments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    matching_roles = await _matching_roles(db, role_assignments)
    role_by_id = {role_id: role_name for role_id, role_name in matching_roles}
    role_by_name = {_normalize_global_role_name(name): role_id for role_id, name in matching_roles}
    role_by_name.update(
        {_normalize_global_role_name(role_by_id[role_id]): role_id for role_id in role_by_id}
    )
    normalized_role_assignments: dict[str, list[str]] = {}
    unknown_role_ids = set()
    for item in role_assignments:
        role_id = _normalize_role_identifier(item.get("role_id") or item.get("role_name"))
        if not role_id:
            role_id = role_by_name.get(_normalize_global_role_name(item.get("role") or item.get("role_id")))
        if not role_id:
            raise HTTPException(status_code=400, detail="Role assignment role_id is required")
        if role_id not in role_by_id:
            unknown_role_ids.add(role_id)
            continue
        normalized_role_assignments[role_id] = _merge_project_roles(
            normalized_role_assignments.get(role_id, []),
            _normalize_project_roles(
                item.get("project_roles") or item.get("project_role") or item.get("role")
            ),
        )
    if unknown_role_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role(s): {', '.join(sorted(unknown_role_ids))}",
        )
    return [
        {
            "role_id": role_id,
            "role": role_by_id[role_id],
            "project_roles": roles,
        }
        for role_id, roles in sorted(normalized_role_assignments.items())
    ]


async def replace_user_rows(
    db: AsyncSession, *, project_id: str, normalized: dict[str, list[str]], granted_by_user_id: str
) -> None:
    await db.execute(sa_delete(UserProject).where(UserProject.project_id == project_id))
    await db.execute(
        sa_delete(ProjectUserRoleAssignment).where(ProjectUserRoleAssignment.project_id == project_id)
    )
    for user_id, roles in sorted(normalized.items()):
        primary = roles[0] if roles else DEFAULT_PROJECT_ACCESS_ROLE
        db.add(
            UserProject(
                user_id=user_id,
                project_id=project_id,
                role=primary,
                granted_by=granted_by_user_id,
            )
        )
        for role_name in roles:
            db.add(
                ProjectUserRoleAssignment(
                    user_id=user_id,
                    project_id=project_id,
                    role_name=role_name,
                )
            )


async def replace_group_rows(
    db: AsyncSession, *, project_id: str, normalized_groups: dict[str, list[str]], granted_by_user_id: str
) -> None:
    await db.execute(sa_delete(ProjectGroup).where(ProjectGroup.project_id == project_id))
    await db.execute(
        sa_delete(ProjectGroupRoleAssignment).where(ProjectGroupRoleAssignment.project_id == project_id)
    )
    for group_id, roles in sorted(normalized_groups.items()):
        primary = roles[0] if roles else DEFAULT_PROJECT_ACCESS_ROLE
        db.add(
            ProjectGroup(
                group_id=group_id,
                project_id=project_id,
                role=primary,
                granted_by=granted_by_user_id,
            )
        )
        for role_name in roles:
            db.add(
                ProjectGroupRoleAssignment(
                    group_id=group_id,
                    project_id=project_id,
                    role_name=role_name,
                )
            )
