"""Read side of project access: the project, its assignments and the user catalog."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    IdentityGroup,
    Project,
    ProjectGroup,
    ProjectGroupRoleAssignment,
    ProjectUserRoleAssignment,
    Role,
    User,
    UserGroup,
    UserProject,
    UserRole,
)
from ._admin_project_access_roles import DEFAULT_PROJECT_ACCESS_ROLE, _extract_project_roles

PROJECT_NOT_FOUND = "Project not found"


async def _get_project(db: AsyncSession, project_id: str) -> Project:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)
    return project



async def _serialize_user_catalog(db: AsyncSession) -> list[dict[str, Any]]:
    users = (await db.execute(select(User).order_by(User.username.asc()))).scalars().all()
    user_ids = [user.id for user in users]
    roles_by_user: dict[str, list[str]] = {}
    groups_by_user: dict[str, list[str]] = {}
    if user_ids:
        role_rows = await db.execute(
            select(UserRole.user_id, Role.name)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
            .order_by(Role.name.asc())
        )
        for user_id, role_name in role_rows.all():
            roles_by_user.setdefault(user_id, []).append(role_name)
        group_rows = await db.execute(
            select(UserGroup.user_id, IdentityGroup.name)
            .join(IdentityGroup, IdentityGroup.id == UserGroup.group_id)
            .where(UserGroup.user_id.in_(user_ids))
            .order_by(IdentityGroup.name.asc())
        )
        for user_id, group_name in group_rows.all():
            groups_by_user.setdefault(user_id, []).append(group_name)
    return [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email or "",
            "display_name": user.display_name or user.username,
            "is_active": bool(user.is_active),
            "roles": roles_by_user.get(user.id, []),
            "groups": groups_by_user.get(user.id, []),
        }
        for user in users
    ]


async def _user_role_assignments(db: AsyncSession, project_id: str) -> dict[str, list[str]]:
    rows = await db.execute(
        select(ProjectUserRoleAssignment.user_id, ProjectUserRoleAssignment.role_name)
        .where(ProjectUserRoleAssignment.project_id == project_id)
        .order_by(ProjectUserRoleAssignment.user_id.asc(), ProjectUserRoleAssignment.role_name.asc())
    )
    roles_by_user: dict[str, list[str]] = {}
    for user_id, role_name in rows.all():
        roles_by_user.setdefault(user_id, []).append(role_name)
    return roles_by_user


async def _group_role_assignments(db: AsyncSession, project_id: str) -> dict[str, list[str]]:
    rows = await db.execute(
        select(ProjectGroupRoleAssignment.group_id, ProjectGroupRoleAssignment.role_name)
        .where(ProjectGroupRoleAssignment.project_id == project_id)
        .order_by(ProjectGroupRoleAssignment.group_id.asc(), ProjectGroupRoleAssignment.role_name.asc())
    )
    roles_by_group: dict[str, list[str]] = {}
    for group_id, role_name in rows.all():
        roles_by_group.setdefault(group_id, []).append(role_name)
    return roles_by_group


async def _serialize_assignments(db: AsyncSession, project_id: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(UserProject, User)
        .join(User, User.id == UserProject.user_id)
        .where(UserProject.project_id == project_id)
        .order_by(User.username.asc())
    )
    roles_by_user = await _user_role_assignments(db, project_id)
    assignments: list[dict[str, Any]] = []
    for assignment, user in rows.all():
        assignments.append(
            {
                "user_id": user.id,
                "username": user.username,
                "email": user.email or "",
                "display_name": user.display_name or user.username,
                "is_active": bool(user.is_active),
                "project_role": assignment.role or DEFAULT_PROJECT_ACCESS_ROLE,
                "project_roles": _extract_project_roles(
                    roles_by_user.get(user.id, []), assignment.role
                ),
                "granted_by": assignment.granted_by,
                "granted_at": assignment.granted_at.isoformat() if assignment.granted_at else None,
            }
        )
    return assignments


async def _serialize_group_assignments(db: AsyncSession, project_id: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(ProjectGroup, IdentityGroup)
        .join(IdentityGroup, IdentityGroup.id == ProjectGroup.group_id)
        .where(ProjectGroup.project_id == project_id)
        .order_by(IdentityGroup.name.asc())
    )
    roles_by_group = await _group_role_assignments(db, project_id)
    assignments: list[dict[str, Any]] = []
    for assignment, group in rows.all():
        assignments.append(
            {
                "group_id": group.id,
                "name": group.name,
                "description": group.description or "",
                "is_active": bool(group.is_active),
                "project_role": assignment.role or DEFAULT_PROJECT_ACCESS_ROLE,
                "project_roles": _extract_project_roles(
                    roles_by_group.get(group.id, []), assignment.role
                ),
                "granted_by": assignment.granted_by,
                "granted_at": assignment.granted_at.isoformat() if assignment.granted_at else None,
            }
        )
    return assignments
