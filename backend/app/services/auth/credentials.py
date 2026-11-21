"""Credentials against the database: username and password, bearer principals and refresh tokens."""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import AuthenticationError

from ...models import RefreshToken, User
from ...time_utils import utc_now, utc_now_aware
from ..api_key import API_KEY_PREFIX, authenticate_api_key
from ..secret import encrypt_secret
from .tokens import _hash_refresh_token, _verify_refresh_token_bcrypt, decode_token, verify_password


async def resolve_bearer_principal_user_id(db: AsyncSession, token: str) -> str:
    """Resolve a Bearer token to a user id for middleware-level observability."""

    raw_token = str(token or "").strip()
    if raw_token.startswith(API_KEY_PREFIX):
        user, _api_key = await authenticate_api_key(db, raw_token)
        return user.id
    return decode_token(raw_token)


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    """Authenticate user by username/password. Returns User or None."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


async def create_refresh_token(
    db: AsyncSession,
    *,
    user_id: str,
    provider_id: str | None = None,
    user_identity_id: str | None = None,
    external_refresh_token: str | None = None,
    expires_delta: timedelta | None = None,
    rotated_from_id: str | None = None,
) -> str:
    raw_token = secrets.token_urlsafe(48)
    token_row = RefreshToken(
        user_id=user_id,
        provider_id=provider_id,
        user_identity_id=user_identity_id,
        token_hash=_hash_refresh_token(raw_token),
        encrypted_external_refresh_token=encrypt_secret(external_refresh_token) if external_refresh_token else None,
        expires_at=utc_now() + (expires_delta or timedelta(days=30)),
        rotated_from_id=rotated_from_id,
    )
    db.add(token_row)
    await db.flush()
    return raw_token


async def rotate_refresh_token(
    db: AsyncSession,
    refresh_token: str,
    *,
    expires_delta: timedelta | None = None,
) -> tuple[User, str, RefreshToken]:
    # bcrypt-of-sha256 — find and verify using work-factor hash
    rows = await db.execute(
        select(RefreshToken).where(
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utc_now_aware(),
        )
    )
    token_row: RefreshToken | None = None
    for row in rows.scalars().all():
        if _verify_refresh_token_bcrypt(refresh_token, row.token_hash):
            token_row = row
            break
    if not token_row:
        raise AuthenticationError("Invalid refresh token")
    user = await db.get(User, token_row.user_id)
    if not user or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    token_row.revoked_at = utc_now()
    token_row.last_used_at = utc_now()
    new_refresh_token = await create_refresh_token(
        db,
        user_id=user.id,
        provider_id=token_row.provider_id,
        user_identity_id=token_row.user_identity_id,
        expires_delta=expires_delta,
        rotated_from_id=token_row.id,
    )
    await db.commit()
    return user, new_refresh_token, token_row


async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> RefreshToken | None:
    token = str(refresh_token or "").strip()
    if not token:
        return None
    rows = await db.execute(
        select(RefreshToken).where(
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utc_now_aware(),
        )
    )
    for row in rows.scalars().all():
        if not _verify_refresh_token_bcrypt(token, row.token_hash):
            continue
        row.revoked_at = utc_now()
        row.last_used_at = utc_now()
        await db.commit()
        return row
    return None
