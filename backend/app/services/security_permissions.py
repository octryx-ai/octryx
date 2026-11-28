"""Permission checks shared by authentication and self-service routes."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Permission, Role, UserRole


async def user_has_permission(db: AsyncSession, user_id: str, *, resource: str, action: str) -> bool:
    role_rows = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    role_names = {str(row[0]) for row in role_rows.all()}
    # Exact match only: "superadmin" / "admin_viewer" must not bypass checks.
    if "admin" in {rn.strip().lower() for rn in role_names}:
        return True

    permission_id = (
        await db.execute(
            select(Permission.id)
            .join(Role, Role.id == Permission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                Permission.resource == resource,
                Permission.action == action,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return permission_id is not None
