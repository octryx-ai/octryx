"""Shared transport helpers of the skill catalog admin API: platform-admin gate and refusal mapping."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.access_control import _user_is_admin
from ....services.auth import get_current_user
from ....services.skill_catalog.errors import SkillCatalogError

CATALOG_PREFIX = "/api/v1/admin/skill-catalog"
ADMIN_FORBIDDEN = "Platform admin role required"


async def require_platform_admin(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    if not await _user_is_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail=ADMIN_FORBIDDEN)
    return current_user


def refused(error: SkillCatalogError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.as_detail())


__all__ = ["ADMIN_FORBIDDEN", "CATALOG_PREFIX", "refused", "require_platform_admin"]
