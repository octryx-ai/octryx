"""Setup guide status. Transport only; platform admins only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.access_control import _user_is_admin
from ....services.auth import get_current_user
from ....services.setup_guide.onboarding_status import onboarding_status

router = APIRouter(prefix="/api/v1/admin/setup", tags=["setup"])


@router.get("/onboarding")
async def get_onboarding_status(
    workspace_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not await _user_is_admin(db, user.id):
        raise HTTPException(status_code=403, detail="Platform admin role required")
    return await onboarding_status(db, workspace_id=workspace_id)


__all__ = ["router"]
