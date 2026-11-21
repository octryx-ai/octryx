"""Server-side enforcement of the "Sign in only through SSO" setting.

``agent.auth_login_mode`` (Settings → Identity → Sign-in & SSO) turns password login off. Every
password login path (``POST /api/v1/auth/login`` and the ``/chat/login`` form) asks
:func:`password_login_disabled` before it looks at the credentials, so the setting cannot be
bypassed by calling the API directly. There is no break-glass exemption: an operator who is
locked out clears the setting in ``system_config`` directly.
"""

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
    """True when the platform only allows sign-in through a configured SSO provider."""
    raw = await get_system_config_value(db, AGENT_AUTH_LOGIN_MODE_KEY)
    return str(raw or "").strip().lower() in _ENABLED_VALUES


async def record_password_login_refused(
    db: AsyncSession, *, username: str, method: str, request: Request | None
) -> None:
    """Audit a refused password attempt against the named account (if it exists) and commit."""
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
