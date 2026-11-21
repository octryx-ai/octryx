"""Project-level access control helpers.

Provides FastAPI-compatible helpers for enforcing project membership
and role-based boundaries consistently across all API routes.

All routes that accept a ``project_id`` parameter (either as a query
parameter or inside a request body) MUST call ``require_project_access``
before proceeding with any service call.

Admin users bypass project membership checks; all other users must be an
explicit member (direct ``user_projects`` row or group-derived via
``project_groups``/``user_groups``).
"""

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
    """Return True if *user_id* holds the ``admin`` role."""
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
    """Return the user's role string in *project_id*, or ``None`` if no access.

    Admins are returned ``"admin"`` regardless of explicit membership, except in somebody else's private
    Workspace: there nobody but its owner has a role (``project.private_workspace``).
    """
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
    """The one answer for a Workspace the caller may not see: an unknown id and a Workspace the caller is no member of
    answer the same 404, so an outsider never learns whether a Workspace exists."""
    return HTTPException(status_code=404, detail={"code": "project_not_found", "message": WORKSPACE_NOT_FOUND_MESSAGE})


async def require_existing_workspace(db: AsyncSession, project_id: str | None) -> None:
    """The existence check of a caller-supplied Workspace id on a platform-admin route, before anything is written for
    it: an id that names no Workspace is 404 ``project_not_found``; an absent one passes. Platform admins see every
    Workspace, so existence reveals nothing to them; who may act in an existing Workspace stays the route's own rule
    (e.g. a private Workspace's owner-only refusal). A route other callers reach uses ``require_visible_workspace``."""
    if project_id and await db.get(Project, project_id) is None:
        raise workspace_not_found()


async def require_visible_workspace(db: AsyncSession, user_id: str, project_id: str | None) -> None:
    """The check of a caller-supplied Workspace id on a route that callers other than platform admins reach: an id
    that names no Workspace and a Workspace the caller is no member of answer the same 404 ``project_not_found``,
    before the route's own permission rule can answer differently. Platform admins pass for every existing Workspace,
    so the route's own rule (e.g. a private Workspace's owner-only refusal) still answers them."""
    if project_id and not await workspace_visible(db, user_id, project_id):
        raise workspace_not_found()


async def workspace_visible(db: AsyncSession, user_id: str, project_id: str) -> bool:
    """Whether ``project_id`` names a Workspace ``user_id`` sees: an existing one, and for anyone but a platform admin
    one they are a member of. A record bound to a Workspace the caller does not see answers like a missing record."""
    if await db.get(Project, project_id) is None:
        return False
    return await _user_is_admin(db, user_id) or await get_project_role_for_user(db, user_id, project_id) is not None


async def require_project_access(
    db: AsyncSession,
    user_id: str,
    project_id: str | None,
    *,
    require_admin: bool = False,
) -> None:
    """Require that *user_id* may act in *project_id*; an absent id passes (optional Workspace parameters).

    An unknown id and a Workspace the caller is no member of both answer 404 ``project_not_found``
    (``workspace_not_found``); a member without the admin/owner role that ``require_admin`` asks for gets 403.
    """
    if not project_id:
        return
    await require_existing_workspace(db, project_id)

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
    """Resolve a required project scope or fail closed when scope is missing."""

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
    """Raise 403 if *requesting_user_id* is not the resource owner and is not admin.

    Useful for task/run access where ownership is the primary boundary.
    """
    if resource_user_id == requesting_user_id:
        return
    if await _user_is_admin(db, requesting_user_id):
        return
    raise HTTPException(status_code=403, detail=error_detail)
