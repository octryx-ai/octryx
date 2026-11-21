from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import IdentityGroup, Permission, Role, User, UserGroup, UserRole
from ...project import get_project_access_details

__all__ = [
    "ADMIN_PANEL_PERMISSIONS",
    "PROJECT_ADMIN_ROLES",
    "has_permission",
    "holds_platform_admin_access",
    "is_admin_capable",
    "is_global_admin",
    "list_effective_access_diagnostics",
]

PROJECT_ADMIN_ROLES = frozenset({"admin", "owner"})
#: The permissions the admin-panel routes delegate to (``_require_admin_permission_api``). A holder of one of them may
#: reach the admin surface (``web/_helpers/admin_surface_gate``); the route still checks the exact one.
ADMIN_PANEL_PERMISSIONS = frozenset(
    {
        ("api_keys", "read"),
        ("api_keys", "write"),
        ("audit", "read"),
        ("identity_providers", "read"),
        ("identity_providers", "write"),
        ("projects", "read"),
        ("projects", "write"),
        ("roles", "read"),
        ("roles", "write"),
        ("users", "read"),
        ("users", "write"),
    }
)


async def is_global_admin(db: AsyncSession, user_id: str) -> bool:
    rows = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return "admin" in {row[0] for row in rows.all()}


async def has_permission(db: AsyncSession, user_id: str, *, resource: str, action: str) -> bool:
    """An active user holding the permission (or the admin role) — the one checker: the role
    lookup is ``security_permissions.user_has_permission``, the same the sign-in and API-key paths ask."""
    from ...security_permissions import user_has_permission

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return False
    return await user_has_permission(db, user_id, resource=resource, action=action)


async def holds_platform_admin_access(db: AsyncSession, user_id: str) -> bool:
    """The admin role or an admin-panel permission: access that the admin-panel routes grant without Workspace
    membership (a Workspace admin/owner's access is their membership)."""
    if await is_global_admin(db, user_id):
        return True
    rows = await db.execute(
        select(Permission.resource, Permission.action)
        .join(Role, Role.id == Permission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return any((resource, action) in ADMIN_PANEL_PERMISSIONS for resource, action in rows.all())


async def is_admin_capable(db: AsyncSession, user_id: str) -> bool:
    """May reach the admin surface at all: the admin role, an admin-panel permission, or a Workspace admin/owner."""
    if await holds_platform_admin_access(db, user_id):
        return True
    access = await get_project_access_details(user_id, db)
    return any(str(item.get("role") or "") in PROJECT_ADMIN_ROLES for item in access)


async def _role_names(db: AsyncSession, user_id: str) -> list[str]:
    rows = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return sorted(row[0] for row in rows.all())


async def _group_names(db: AsyncSession, user_id: str) -> list[str]:
    rows = await db.execute(
        select(IdentityGroup.name)
        .join(UserGroup, UserGroup.group_id == IdentityGroup.id)
        .where(UserGroup.user_id == user_id)
        .order_by(IdentityGroup.name)
    )
    return [row[0] for row in rows.all()]


async def _permissions(db: AsyncSession, user_id: str) -> list[dict[str, str]]:
    rows = await db.execute(
        select(Permission.resource, Permission.action)
        .join(Role, Role.id == Permission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .order_by(Permission.resource, Permission.action)
    )
    seen: set[tuple[str, str]] = set()
    payload: list[dict[str, str]] = []
    for resource, action in rows.all():
        key = (resource, action)
        if key in seen:
            continue
        seen.add(key)
        payload.append({"resource": resource, "action": action})
    return payload


async def _assigned_projects(db: AsyncSession, user_id: str) -> list[dict[str, str]]:
    return await get_project_access_details(user_id, db)


async def list_effective_access_diagnostics(db: AsyncSession) -> list[dict[str, object]]:
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    diagnostics: list[dict[str, object]] = []
    for user in users:
        roles = await _role_names(db, user.id)
        groups = await _group_names(db, user.id)
        permissions = await _permissions(db, user.id)
        assigned_projects = await _assigned_projects(db, user.id)
        # Access check: every answer comes from the gate the platform runs, never a parallel rule.
        can_use_chat = bool(user.is_active) and await has_permission(db, user.id, resource="auth", action="login")
        can_open_admin_panel = bool(user.is_active) and await is_admin_capable(db, user.id)
        diagnostics.append(
            {
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email or "",
                    "display_name": user.display_name or user.username,
                    "is_active": bool(user.is_active),
                },
                "roles": roles,
                "groups": groups,
                "permissions": permissions,
                "assigned_projects": assigned_projects,
                "effective": {
                    "can_use_chat": can_use_chat,
                    "can_open_admin_panel": can_open_admin_panel,
                    "visible_project_count": len(assigned_projects) if user.is_active else 0,
                    "assigned_project_count": len(assigned_projects),
                },
                "rules": [
                    "Sign-in and chat: an active account with the auth:login permission (the sign-in check).",
                    "Admin surface: the admin role, an admin-panel permission, or admin/owner of a Workspace "
                    "(the admin surface gate); each page still checks its own permission.",
                    "Workspaces: direct assignments and active group-derived assignments.",
                ],
            }
        )
    return diagnostics
