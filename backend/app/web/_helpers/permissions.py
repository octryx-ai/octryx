"""Shared permission evaluation helpers for web-facing admin checks."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...services.admin.governance.admin_access_service import has_permission, is_global_admin

__all__ = [
    "require_global_admin",
    "require_permission",
]


async def require_global_admin(db: AsyncSession, current_user: User, *, detail: str = "Admin access required") -> None:
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def require_permission(
    db: AsyncSession,
    current_user: User,
    *,
    resource: str,
    action: str,
    detail: str | None = None,
) -> None:
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    if not await has_permission(db, current_user.id, resource=resource, action=action):
        required = f"{resource}:{action}"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail or f"Permission required: {required}",
        )
