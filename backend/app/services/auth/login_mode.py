"""Server-side enforcement of the "Sign in only through SSO" setting."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..system_config import get_system_config_value
from ..system_config.constants import AGENT_AUTH_LOGIN_MODE_KEY
from .audit import record_auth_audit_event

PASSWORD_LOGIN_DISABLED_DETAIL = "Password login is disabled. Please use SSO."

_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})


async def password_login_disabled(db: AsyncSession) -> bool:
    raw = await get_system_config_value(db, AGENT_AUTH_LOGIN_MODE_KEY)
    return str(raw or "").strip().lower() in _ENABLED_VALUES


async def record_password_login_refused(
    db: AsyncSession, *, username: str, method: str, request: Request | None
) -> None:
    user_id = (await db.execute(select(User.id).where(User.username == username))).scalar_one_or_none()
    record_auth_audit_event(
        db,
        user_id=user_id,
        action="auth.login.blocked",
        details={"reason": "password_login_disabled", "method": method, "username": username},
        request=request,
    )
    await db.commit()


__all__ = ["PASSWORD_LOGIN_DISABLED_DETAIL", "password_login_disabled", "record_password_login_refused"]
