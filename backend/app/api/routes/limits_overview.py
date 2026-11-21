"""Runtime → Execution → Limits & budgets overview. Transport only; platform admins only.

- ``GET /api/v1/admin/limits/overview`` — Workspace overrides per limit, environment rate limits (read-only),
  budget periods with this period's spend. Values are saved through the runtime settings and budget policy APIs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import _user_is_admin
from ...services.auth import get_current_user
from ...services.limits.overview import limits_overview

router = APIRouter(prefix="/api/v1/admin/limits", tags=["limits"])


@router.get("/overview")
async def get_limits_overview(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    if not await _user_is_admin(db, user.id):
        raise HTTPException(status_code=403, detail="Platform admin role required")
    return await limits_overview(db)


__all__ = ["router"]
