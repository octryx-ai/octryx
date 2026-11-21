"""Admin guard shared by the control plane page routers."""

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.web._helpers.auth import _require_user

from ...services.notification_delivery import require_admin_user


async def _require_control_plane_admin_or_login_redirect(request: Request, db: AsyncSession):
    try:
        user = await _require_user(request, db)
    except HTTPException:
        return None, RedirectResponse(url="/chat/login", status_code=303)
    await require_admin_user(db, user)
    return user, None
