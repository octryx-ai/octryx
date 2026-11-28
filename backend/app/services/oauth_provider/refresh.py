"""Refresh-token rotation and revocation for the platform OAuth server."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.security.oauth_provider import OAuthClient, OAuthGrant, OAuthRefreshToken
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from .flows import (
    OAuthFlowError,
    _issue_refresh_token,
    _login_session_alive,
    _require_device_audience_binding,
    _token_response,
)
from .tokens import hash_token


async def refresh_with_token(
    db: AsyncSession,
    *,
    client: OAuthClient,
    refresh_token: str,
    resource: str | None = None,
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(OAuthRefreshToken).where(OAuthRefreshToken.token_hash == hash_token(refresh_token))
        )
    ).scalar_one_or_none()
    if row is None or row.client_id != client.client_id:
        raise OAuthFlowError("invalid_grant", "Unknown refresh token")

    grant = await db.get(OAuthGrant, row.grant_id)
    if grant is None or grant.revoked_at is not None:
        raise OAuthFlowError("invalid_grant", "Grant is revoked")

    if row.revoked_at is not None:
        # Replay of a rotated token: treat as theft, kill the whole grant.
        grant.revoked_at = utc_now()
        await db.commit()
        raise OAuthFlowError("invalid_grant", "Refresh token replay detected; grant revoked")
    if ensure_utc(row.expires_at) <= utc_now_aware():
        raise OAuthFlowError("invalid_grant", "Refresh token expired")
    if grant.device_id:
        # A device grant is bound to its device registration, not to the web login session.
        from ..devices.credential import device_grant_refusal

        if await device_grant_refusal(db, grant):
            raise OAuthFlowError("invalid_grant", "Device credential is no longer valid; enable the device again")
    elif not await _login_session_alive(db, grant.platform_refresh_token_id):
        raise OAuthFlowError("invalid_grant", "Platform login session has ended; re-authorization required")
    _require_device_audience_binding(grant, resource)

    row.revoked_at = utc_now()
    scopes = list(row.scopes or [])
    new_refresh = await _issue_refresh_token(
        db, grant=grant, client_id=client.client_id, scopes=scopes, rotated_from_id=row.id
    )
    await db.commit()
    return _token_response(
        grant=grant,
        client_id=client.client_id,
        scopes=scopes,
        resource=resource,
        refresh_token=new_refresh,
    )


async def revoke_token(db: AsyncSession, *, client: OAuthClient, token: str) -> bool:
    """RFC 7009: revoke a refresh token (access tokens expire on their own)."""
    row = (
        await db.execute(
            select(OAuthRefreshToken).where(OAuthRefreshToken.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()
    if row is None or row.client_id != client.client_id:
        return False
    if row.revoked_at is None:
        row.revoked_at = utc_now()
    grant = await db.get(OAuthGrant, row.grant_id)
    if grant is not None and grant.revoked_at is None:
        grant.revoked_at = utc_now()
    await db.commit()
    return True
