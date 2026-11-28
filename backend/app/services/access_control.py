"""Project-level access control helpers. Every route that takes a ``project_id`` must call ``require_project_access``
first."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project, Role, UserRole


@dataclass(frozen=True, slots=True)
class ProjectScopeContext:
    user_id: str
    project_id: str
    project_role: str
    project_admin: bool


async def _user_is_admin(db: AsyncSession, user_id: str) -> bool:
    rows = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return "admin" in {str(r[0]).strip().lower() for r in rows.all()}


async def get_project_role_for_user(
    db: AsyncSession,
    user_id: str,
    project_id: str,
) -> str | None:
    # Admins get ``admin`` everywhere except in somebody else's private Workspace, where only its owner has a role.
    from .project.private_workspace import private_project, private_role  # noqa: PLC0415

    private = await private_project(db, project_id)
    if private is not None:
        return private_role(private, user_id)
    if await _user_is_admin(db, user_id):
        return "admin"

    from .project.service import get_project_access_details

    access = await get_project_access_details(user_id, db)
    for item in access:
        if item["id"] == project_id:
            return item.get("role", "member")
    return None


WORKSPACE_NOT_FOUND_MESSAGE = "The named Workspace does not exist."


def workspace_not_found() -> HTTPException:
    # Unknown and not-a-member answer the same 404, so an outsider never learns whether a Workspace exists.
    return HTTPException(status_code=404, detail={"code": "project_not_found", "message": WORKSPACE_NOT_FOUND_MESSAGE})


async def require_existing_workspace(db: AsyncSession, user_id: str, project_id: str | None) -> None:
    # Somebody else's private Workspace does not exist for the caller, platform admins included.
    from .project.private_workspace import foreign_private  # noqa: PLC0415

    if not project_id:
        return
    project = await db.get(Project, project_id)
    if project is None or foreign_private(project, user_id):
        raise workspace_not_found()


async def require_visible_workspace(db: AsyncSession, user_id: str, project_id: str | None) -> None:
    # Unknown and not-a-member answer the same 404 before the route's own permission rule can answer differently.
    if project_id and not await workspace_visible(db, user_id, project_id):
        raise workspace_not_found()


async def workspace_visible(db: AsyncSession, user_id: str, project_id: str) -> bool:
    # A record bound to a Workspace the caller does not see answers like a missing record.
    if await db.get(Project, project_id) is None:
        return False
    return await get_project_role_for_user(db, user_id, project_id) is not None


async def require_project_access(
    db: AsyncSession,
    user_id: str,
    project_id: str | None,
    *,
    require_admin: bool = False,
) -> None:
    if not project_id:
        return
    await require_existing_workspace(db, user_id, project_id)

    role = await get_project_role_for_user(db, user_id, project_id)
    if role is None:
        raise workspace_not_found()

    if require_admin and role not in {"admin", "owner"}:
        raise HTTPException(
            status_code=403,
            detail="Project admin or owner role required for this action.",
        )


async def require_project_scope(
    db: AsyncSession,
    user_id: str,
    project_id: str | None,
    *,
    require_admin: bool = False,
) -> ProjectScopeContext:
    # Fail closed when the scope is missing.

    resolved_project_id = str(project_id or "").strip()
    if not resolved_project_id:
        raise HTTPException(status_code=400, detail="Project scope is required for this operation.")

    role = await get_project_role_for_user(db, user_id, resolved_project_id)
    if role is None or await db.get(Project, resolved_project_id) is None:
        raise workspace_not_found()
    project_admin = role in {"admin", "owner"}
    if require_admin and not project_admin:
        raise HTTPException(
            status_code=403,
            detail="Project admin or owner role required for this action.",
        )
    return ProjectScopeContext(
        user_id=user_id,
        project_id=resolved_project_id,
        project_role=role,
        project_admin=project_admin,
    )


async def assert_user_owns_resource(
    resource_user_id: str,
    requesting_user_id: str,
    db: AsyncSession,
    *,
    error_detail: str = "Access denied: you do not own this resource.",
) -> None:
    if resource_user_id == requesting_user_id:
        return
    if await _user_is_admin(db, requesting_user_id):
        return
    raise HTTPException(status_code=403, detail=error_detail)
