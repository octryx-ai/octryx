"""The API dependency for admin-only mutations."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from .service import get_current_user

ADMIN_ACCESS_REQUIRED_DETAIL = "Admin access required"


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    from ..admin.governance.admin_access_service import is_global_admin

    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_ACCESS_REQUIRED_DETAIL)
    return current_user


__all__ = ["ADMIN_ACCESS_REQUIRED_DETAIL", "get_current_admin_user"]
