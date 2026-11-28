"""A platform logout forces reauthorization, a platform session rotation keeps the grant alive, and the revocation endpoint kills the grant."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken, User
from app.services.auth import create_refresh_token
from tests.support.oauth_provider_support import _approve_consent, _login_cookies, _pkce_pair, _register_client


@pytest.mark.asyncio
async def test_platform_logout_forces_reauthorization(client, db: AsyncSession):
    registration = await _register_client(client)
    verifier, challenge = _pkce_pair()
    await _login_cookies(client)
    code = await _approve_consent(client, registration, challenge)
    token_response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": registration["redirect_uris"][0],
            "code_verifier": verifier,
            "client_id": registration["client_id"],
        },
    )
    assert token_response.status_code == 200, token_response.text
    refresh_token_value = token_response.json()["refresh_token"]

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    rows = (
        (await db.execute(select(RefreshToken).where(RefreshToken.user_id == admin.id)))
        .scalars()
        .all()
    )
    from app.time_utils import utc_now

    for row in rows:
        row.revoked_at = utc_now()
    await db.commit()

    refreshed = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token_value,
            "client_id": registration["client_id"],
        },
    )
    assert refreshed.status_code == 400
    body = refreshed.json()
    assert body["error"] == "invalid_grant"
    assert "login session" in body["error_description"]


@pytest.mark.asyncio
async def test_platform_session_rotation_keeps_grant_alive(client, db: AsyncSession):
    registration = await _register_client(client)
    verifier, challenge = _pkce_pair()
    await _login_cookies(client)
    code = await _approve_consent(client, registration, challenge)
    tokens = (
        await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": registration["redirect_uris"][0],
                "code_verifier": verifier,
                "client_id": registration["client_id"],
            },
        )
    ).json()

    # Simulate the platform session rotating (as /api/v1/auth/refresh does):
    # revoke the newest row but chain a successor to it.
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    newest = (
        await db.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == admin.id, RefreshToken.revoked_at.is_(None))
            .order_by(RefreshToken.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    from app.time_utils import utc_now

    newest.revoked_at = utc_now()
    await create_refresh_token(db, user_id=admin.id, rotated_from_id=newest.id)
    await db.commit()

    refreshed = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": registration["client_id"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text


@pytest.mark.asyncio
async def test_revocation_endpoint_kills_grant(client, db):
    registration = await _register_client(client)
    verifier, challenge = _pkce_pair()
    await _login_cookies(client)
    code = await _approve_consent(client, registration, challenge)
    tokens = (
        await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": registration["redirect_uris"][0],
                "code_verifier": verifier,
                "client_id": registration["client_id"],
            },
        )
    ).json()

    revoke = await client.post(
        "/oauth/revoke",
        data={"token": tokens["refresh_token"], "client_id": registration["client_id"]},
    )
    assert revoke.status_code == 200

    refreshed = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": registration["client_id"],
        },
    )
    assert refreshed.status_code == 400
