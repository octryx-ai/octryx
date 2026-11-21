"""The guard of the server-rendered ``/admin`` pages and their form posts.

These routes answer a missing principal with the login redirect, as every page route does, and
an active non-admin with 403 (``Admin role required``) through the platform's
``require_global_admin``. The admin-surface gate (``admin_surface_gate.py``) refuses a non-admin
on the form posts before the route runs; this guard is the route's own check, and the only one on
the page ``GET`` routes.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from .auth import _require_user
from .permissions import require_global_admin

ADMIN_ROLE_REQUIRED_DETAIL = "Admin role required"


class LoginRequiredError(Exception):
    """No active principal: the page route answers with the login redirect."""


async def require_page_admin(request: Request, db: AsyncSession) -> User:
    """Active admin, 403 for any other active user, :class:`LoginRequiredError` without a principal."""
    try:
        user = await _require_user(request, db)
    except HTTPException:
        raise LoginRequiredError from None
    await require_global_admin(db, user, detail=ADMIN_ROLE_REQUIRED_DETAIL)
    return user


__all__ = ["ADMIN_ROLE_REQUIRED_DETAIL", "LoginRequiredError", "require_page_admin"]
