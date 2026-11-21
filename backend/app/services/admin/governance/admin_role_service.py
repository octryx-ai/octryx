"""Admin-panel service helpers for role catalog management."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Permission, Role, User, UserRole
from ...auth.audit import record_auth_audit_event
from ...security_scope_contract import permission_catalog, permission_keys

CORE_ROLE_NAMES = {"admin", "operator", "technical", "viewer"}
_ROLE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
PERMISSION_CATALOG: tuple[dict[str, str], ...] = tuple(permission_catalog())
_PERMISSION_KEYS = permission_keys()


def _normalize_role_name(value: str) -> str:
    name = str(value or "").strip().lower()
    if not _ROLE_NAME_PATTERN.fullmatch(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role name must be 2-64 lowercase characters and may contain numbers, '_' or '-'.",
        )
    return name


def _normalize_permissions(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Permissions must be a list")
    normalized: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Permission entries must be objects")
        resource = str(item.get("resource") or "").strip().lower()
        action = str(item.get("action") or "").strip().lower()
        if (resource, action) not in _PERMISSION_KEYS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported permission '{resource}:{action}'",
            )
        normalized.add((resource, action))
    return [{"resource": resource, "action": action} for resource, action in sorted(normalized)]


def _serialize_permissions(permissions: list[Permission]) -> list[dict[str, str]]:
    return [
        {"resource": permission.resource, "action": permission.action}
        for permission in sorted(permissions, key=lambda item: (item.resource, item.action))
    ]


def _serialize_role(
    role: Role,
    user_count: int,
    permissions: list[Permission] | None = None,
    assigned_users: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description or "",
        "is_core": role.name in CORE_ROLE_NAMES,
        "user_count": user_count,
        "permissions": _serialize_permissions(permissions or []),
        "assigned_users": assigned_users or [],
    }


async def list_permission_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in PERMISSION_CATALOG]


async def _role_permissions(db: AsyncSession, role_id: str) -> list[Permission]:
    return (await db.execute(select(Permission).where(Permission.role_id == role_id))).scalars().all()


def _role_audit_snapshot(role: Role, permissions: list[Permission]) -> dict[str, Any]:
    return {
        "name": role.name,
        "description": role.description or "",
        "is_core": role.name in CORE_ROLE_NAMES,
        "permissions": _serialize_permissions(permissions),
    }


async def list_roles(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Role, func.count(UserRole.user_id))
        .outerjoin(UserRole, UserRole.role_id == Role.id)
        .group_by(Role.id)
        .order_by(Role.name)
    )
    roles = rows.all()
    role_ids = [role.id for role, _user_count in roles]
    permission_rows = await db.execute(select(Permission).where(Permission.role_id.in_(role_ids))) if role_ids else None
    permissions_by_role: dict[str, list[Permission]] = {}
    if permission_rows is not None:
        for permission in permission_rows.scalars().all():
            permissions_by_role.setdefault(permission.role_id, []).append(permission)
    assigned_users_by_role: dict[str, list[dict[str, str]]] = {}
    if role_ids:
        user_rows = await db.execute(
            select(UserRole.role_id, User.id, User.username, User.email)
            .join(User, User.id == UserRole.user_id)
            .where(UserRole.role_id.in_(role_ids))
            .order_by(User.username)
        )
        for role_id, user_id, username, email in user_rows.all():
            assigned_users_by_role.setdefault(role_id, []).append(
                {"id": user_id, "username": username, "email": email or ""}
            )
    return [
        _serialize_role(
            role,
            int(user_count or 0),
            permissions_by_role.get(role.id, []),
            assigned_users_by_role.get(role.id, []),
        )
        for role, user_count in roles
    ]


async def create_role(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    admin_id: str | None = None,
) -> dict[str, Any]:
    name = _normalize_role_name(str(payload.get("name") or ""))
    description = str(payload.get("description") or "").strip()
    existing = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Role '{name}' already exists")
    role = Role(name=name, description=description)
    db.add(role)
    await db.flush()
    for permission in _normalize_permissions(payload.get("permissions")):
        db.add(Permission(role_id=role.id, resource=permission["resource"], action=permission["action"]))
    await db.commit()
    await db.refresh(role)
    permissions = await _role_permissions(db, role.id)
    record_auth_audit_event(
        db,
        user_id=admin_id,
        action="admin.role.created",
        resource_type="role",
        resource_id=role.id,
        details={"after": _role_audit_snapshot(role, list(permissions))},
    )
    if admin_id:
        await db.commit()
    return _serialize_role(role, 0, list(permissions))


async def update_role(
    db: AsyncSession,
    *,
    role_id: str,
    payload: dict[str, Any],
    admin_id: str | None = None,
) -> dict[str, Any]:
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    before = _role_audit_snapshot(role, await _role_permissions(db, role.id))
    if "name" in payload and str(payload.get("name") or "").strip().lower() != role.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role names are immutable because policies reference them by name.",
        )
    if "description" in payload:
        role.description = str(payload.get("description") or "").strip()
    if "permissions" in payload:
        if role.name in CORE_ROLE_NAMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Core role permissions are protected because authorization still references core role names.",
            )
        permissions = _normalize_permissions(payload.get("permissions"))
        await db.execute(sa_delete(Permission).where(Permission.role_id == role.id))
        for permission in permissions:
            db.add(Permission(role_id=role.id, resource=permission["resource"], action=permission["action"]))
    after = _role_audit_snapshot(role, await _role_permissions(db, role.id))
    record_auth_audit_event(
        db,
        user_id=admin_id,
        action="admin.role.updated",
        resource_type="role",
        resource_id=role.id,
        details={"changed_keys": sorted(str(key) for key in payload.keys()), "before": before, "after": after},
    )
    await db.commit()
    await db.refresh(role)
    count = (
        await db.execute(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id))
    ).scalar_one()
    permissions = await _role_permissions(db, role.id)
    return _serialize_role(role, int(count or 0), list(permissions))


async def delete_role(db: AsyncSession, *, role_id: str, admin_id: str | None = None) -> dict[str, Any]:
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    if role.name in CORE_ROLE_NAMES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Core roles cannot be deleted")
    count = (
        await db.execute(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id))
    ).scalar_one()
    if int(count or 0) > 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete a role assigned to users")
    before = _role_audit_snapshot(role, await _role_permissions(db, role.id))
    await db.execute(sa_delete(Permission).where(Permission.role_id == role.id))
    record_auth_audit_event(
        db,
        user_id=admin_id,
        action="admin.role.deleted",
        resource_type="role",
        resource_id=role.id,
        details={"before": before},
    )
    await db.delete(role)
    await db.commit()
    return {"status": "deleted"}
