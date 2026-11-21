"""Authorization-code flow for the platform OAuth server (refresh rotation and revocation: ``refresh``).

Security posture:
- PKCE S256 is mandatory (OAuth 2.1); "plain" is rejected.
- Authorization codes are single-use with a 10-minute TTL.
- Refresh tokens rotate on every use; replaying a rotated token revokes the
  whole grant (token-theft signal).
- Every refresh checks that the platform login session captured at consent
  time is still alive (rotation-chain walk). Platform logout or session
  expiry therefore forces the external client back through /oauth/authorize.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import RefreshToken
from ...models.security.oauth_provider import (
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthGrant,
    OAuthRefreshToken,
)
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from .tokens import hash_token, mint_access_token

AUTHORIZATION_CODE_TTL = timedelta(minutes=10)
OAUTH_REFRESH_TOKEN_TTL = timedelta(days=30)
_LOGIN_CHAIN_MAX_HOPS = 500


class OAuthFlowError(Exception):
    """OAuth error with a spec-conformant error code."""

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")


async def find_reusable_grant(
    db: AsyncSession,
    *,
    user_id: str,
    client_id: str,
    scopes: list[str],
) -> OAuthGrant | None:
    """Return an unrevoked grant covering the requested scopes, if any."""
    rows = (
        (
            await db.execute(
                select(OAuthGrant).where(
                    OAuthGrant.user_id == user_id,
                    OAuthGrant.client_id == client_id,
                    OAuthGrant.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for grant in rows:
        if set(scopes).issubset(set(grant.scopes or [])):
            return grant
    return None


async def create_grant(
    db: AsyncSession,
    *,
    user_id: str,
    client_id: str,
    scopes: list[str],
    project_ids: list[str] | None,
    platform_refresh_token_id: str | None,
) -> OAuthGrant:
    grant = OAuthGrant(
        user_id=user_id,
        client_id=client_id,
        scopes=list(scopes),
        project_ids=project_ids,
        platform_refresh_token_id=platform_refresh_token_id,
    )
    db.add(grant)
    await db.flush()
    return grant


async def issue_authorization_code(
    db: AsyncSession,
    *,
    grant: OAuthGrant,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    code_challenge: str,
    code_challenge_method: str,
    resource: str | None,
) -> str:
    if code_challenge_method != "S256":
        raise OAuthFlowError("invalid_request", "code_challenge_method must be S256")
    if not code_challenge:
        raise OAuthFlowError("invalid_request", "code_challenge is required (PKCE)")
    raw_code = secrets.token_urlsafe(48)
    db.add(
        OAuthAuthorizationCode(
            code_hash=hash_token(raw_code),
            client_id=client_id,
            grant_id=grant.id,
            user_id=grant.user_id,
            redirect_uri=redirect_uri,
            scopes=list(scopes),
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
            expires_at=utc_now() + AUTHORIZATION_CODE_TTL,
        )
    )
    await db.commit()
    return raw_code


async def _login_session_alive(db: AsyncSession, platform_refresh_token_id: str | None) -> bool:
    """Walk the platform refresh-token rotation chain; the newest link must live."""
    if not platform_refresh_token_id:
        return False
    current = await db.get(RefreshToken, platform_refresh_token_id)
    hops = 0
    while current is not None and hops < _LOGIN_CHAIN_MAX_HOPS:
        successor = (
            await db.execute(select(RefreshToken).where(RefreshToken.rotated_from_id == current.id))
        ).scalar_one_or_none()
        if successor is None:
            break
        current = successor
        hops += 1
    if current is None:
        return False
    if current.revoked_at is not None:
        return False
    return ensure_utc(current.expires_at) > utc_now_aware()


async def _issue_refresh_token(
    db: AsyncSession,
    *,
    grant: OAuthGrant,
    client_id: str,
    scopes: list[str],
    rotated_from_id: str | None = None,
) -> str:
    raw = secrets.token_urlsafe(48)
    db.add(
        OAuthRefreshToken(
            token_hash=hash_token(raw),
            grant_id=grant.id,
            client_id=client_id,
            user_id=grant.user_id,
            scopes=list(scopes),
            expires_at=utc_now() + OAUTH_REFRESH_TOKEN_TTL,
            rotated_from_id=rotated_from_id,
        )
    )
    return raw


def _require_device_audience_binding(grant: OAuthGrant, resource: str | None) -> None:
    """The device channel audience is minted for device grants only."""
    from ..devices.contract import DEVICE_AUDIENCE

    if resource == DEVICE_AUDIENCE and not grant.device_id:
        raise OAuthFlowError("invalid_target", "The requested resource is not served by this platform")


def _token_response(
    *,
    grant: OAuthGrant,
    client_id: str,
    scopes: list[str],
    resource: str | None,
    refresh_token: str,
) -> dict[str, Any]:
    from ..devices.contract import DEVICE_ACCESS_TOKEN_MINUTES, DEVICE_AUDIENCE

    access_token, expires_in = mint_access_token(
        user_id=grant.user_id,
        client_id=client_id,
        grant_id=grant.id,
        scopes=scopes,
        resource=resource,
        expires_minutes=DEVICE_ACCESS_TOKEN_MINUTES if resource == DEVICE_AUDIENCE else None,
    )
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": refresh_token,
        "scope": " ".join(scopes),
    }


async def exchange_authorization_code(
    db: AsyncSession,
    *,
    client: OAuthClient,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    resource: str | None = None,
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code_hash == hash_token(code))
        )
    ).scalar_one_or_none()
    if row is None or row.client_id != client.client_id:
        raise OAuthFlowError("invalid_grant", "Unknown authorization code")
    if row.consumed_at is not None:
        raise OAuthFlowError("invalid_grant", "Authorization code already used")
    if ensure_utc(row.expires_at) <= utc_now_aware():
        raise OAuthFlowError("invalid_grant", "Authorization code expired")
    if row.redirect_uri != redirect_uri:
        raise OAuthFlowError("invalid_grant", "redirect_uri does not match the authorization request")
    if not code_verifier or _s256(code_verifier) != row.code_challenge:
        raise OAuthFlowError("invalid_grant", "PKCE verification failed")

    grant = await db.get(OAuthGrant, row.grant_id)
    if grant is None or grant.revoked_at is not None:
        raise OAuthFlowError("invalid_grant", "Grant is revoked")
    if not await _login_session_alive(db, grant.platform_refresh_token_id):
        raise OAuthFlowError("invalid_grant", "Platform login session has ended; re-authorization required")
    _require_device_audience_binding(grant, resource or row.resource)

    row.consumed_at = utc_now()
    scopes = list(row.scopes or [])
    resource_value = resource or row.resource
    refresh_token = await _issue_refresh_token(db, grant=grant, client_id=client.client_id, scopes=scopes)
    await db.commit()
    return _token_response(
        grant=grant,
        client_id=client.client_id,
        scopes=scopes,
        resource=resource_value,
        refresh_token=refresh_token,
    )
