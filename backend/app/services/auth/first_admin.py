"""First-start admin setup: no built-in admin password."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import User
from .tokens import hash_password

logger = logging.getLogger(__name__)

ADMIN_USERNAME = "admin"
AUTH_SOURCE_SETUP_PENDING = "setup_pending"
AUTH_SOURCE_LOCAL = "local"
MIN_PASSWORD_CHARS = 12
SETUP_PATH = "/chat/setup"
_CODE_CONTEXT = b"octryx-first-admin-setup-v1:"


class FirstAdminSetupClosedError(Exception):
    pass


class FirstAdminSetupRejectedError(ValueError):
    pass


@dataclass(frozen=True)
class SeedCredential:
    password_hash: str
    auth_source: str


def seed_credential() -> SeedCredential:
    configured = get_settings().admin_default_password
    if configured:
        return SeedCredential(hash_password(configured), AUTH_SOURCE_LOCAL)
    return SeedCredential(hash_password(secrets.token_urlsafe(48)), AUTH_SOURCE_SETUP_PENDING)


def setup_code(admin_user_id: str) -> str:
    digest = hmac.new(
        get_settings().jwt_secret.encode("utf-8"), _CODE_CONTEXT + admin_user_id.encode("utf-8"), hashlib.sha256
    ).digest()
    raw = base64.b32encode(digest).decode("ascii")[:12]
    return "-".join(raw[i : i + 4] for i in range(0, 12, 4))


def _normalize_code(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


async def pending_admin(db: AsyncSession) -> User | None:
    user = (await db.execute(select(User).where(User.username == ADMIN_USERNAME))).scalar_one_or_none()
    if user is not None and user.auth_source == AUTH_SOURCE_SETUP_PENDING:
        return user
    return None


def log_setup_code(admin_user: User) -> None:
    origin = (get_settings().platform_public_origin or "").rstrip("/")
    sys.stderr.write(
        f"[setup] No administrator yet. Open {origin}{SETUP_PATH} and enter the setup code "
        f"{setup_code(admin_user.id)}\n"
    )
    sys.stderr.flush()
    logger.warning("No administrator yet; the one-time code is on the API's standard error output.")


async def complete_first_admin(
    db: AsyncSession, *, code: str, display_name: str, email: str, password: str
) -> User:
    user = await pending_admin(db)
    if user is None:
        raise FirstAdminSetupClosedError()
    if not hmac.compare_digest(_normalize_code(code), _normalize_code(setup_code(user.id))):
        raise FirstAdminSetupRejectedError("The setup code is not correct. Copy it from the server log.")
    name = str(display_name or "").strip()
    address = str(email or "").strip()
    if not name:
        raise FirstAdminSetupRejectedError("Enter your name.")
    if "@" not in address or len(address) > 255:
        raise FirstAdminSetupRejectedError("Enter a valid e-mail address.")
    if len(password or "") < MIN_PASSWORD_CHARS:
        raise FirstAdminSetupRejectedError(f"The password needs at least {MIN_PASSWORD_CHARS} characters.")
    clash = (
        await db.execute(select(User.id).where(User.email == address, User.id != user.id))
    ).scalar_one_or_none()
    if clash is not None:
        raise FirstAdminSetupRejectedError("This e-mail address already belongs to another account.")
    user.display_name = name[:200]
    user.email = address
    user.password_hash = hash_password(password)
    user.auth_source = AUTH_SOURCE_LOCAL
    user.is_active = True
    await db.flush()
    return user
