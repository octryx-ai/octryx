"""The guard of the server-rendered ``/admin`` pages and their form posts."""

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from .auth import _require_user
from .permissions import require_global_admin

ADMIN_ROLE_REQUIRED_DETAIL = "Admin role required"


class LoginRequiredError(Exception):
    pass


async def require_page_admin(request: Request, db: AsyncSession) -> User:
    try:
        user = await _require_user(request, db)
    except HTTPException:
        raise LoginRequiredError from None
    await require_global_admin(db, user, detail=ADMIN_ROLE_REQUIRED_DETAIL)
    return user


__all__ = ["ADMIN_ROLE_REQUIRED_DETAIL", "LoginRequiredError", "require_page_admin"]
