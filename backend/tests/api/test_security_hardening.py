"""Focused security hardening regression tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.api.routes.identity.auth as api_auth_module
import app.services.oidc.service as oidc_service_module
from app.models import IdentityProvider, RefreshToken, User, UserIdentity
from app.services.auth import create_access_token
from tests.conftest import ADMIN_PASSWORD, send_without_origin


@pytest.mark.asyncio
async def test_admin_login_sets_hardened_cookie_attributes(client):
    response = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )

    assert response.status_code == 303
    set_cookie = "\n".join(response.headers.get_list("set-cookie"))
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie


@pytest.mark.asyncio
async def test_oidc_callback_sets_hardened_cookie_attributes(client, db):
    provider = IdentityProvider(
        name="Example SSO",
        provider_type="oidc",
        issuer_url="https://issuer.example.com",
        client_id="client-123",
        authorization_endpoint="https://issuer.example.com/auth",
        token_endpoint="https://issuer.example.com/token",
        userinfo_endpoint="https://issuer.example.com/userinfo",
        scopes_json=["openid", "profile", "email", "groups"],
        group_role_mappings_json={"octryx-admins": ["admin"]},
        auto_provision_users=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_discover(_provider):
        return {
            "authorization_endpoint": "https://issuer.example.com/auth",
            "token_endpoint": "https://issuer.example.com/token",
            "userinfo_endpoint": "https://issuer.example.com/userinfo",
        }

    async def fake_exchange_authorization_code(**kwargs):
        assert kwargs["code"] == "oidc-code-1"
        return {
            "access_token": "access-token-1",
            "refresh_token": "provider-refresh-1",
        }

    async def fake_fetch_userinfo_claims(_userinfo_endpoint, _access_token):
        return {
            "sub": "user-sub-123",
            "email": "oidc-user@example.com",
            "preferred_username": "oidc-user",
            "name": "OIDC User",
            "groups": ["octryx-admins"],
        }

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(oidc_service_module, "_discover_provider_configuration", fake_discover)
    monkeypatch.setattr(oidc_service_module, "_exchange_authorization_code", fake_exchange_authorization_code)
    monkeypatch.setattr(oidc_service_module, "_fetch_userinfo_claims", fake_fetch_userinfo_claims)
    try:
        start_response = await client.get(
            f"/api/v1/auth/oidc/start/{provider.id}?target=/admin/chat",
            follow_redirects=False,
        )
        assert start_response.status_code == 307
        state = start_response.headers["location"].split("state=", 1)[1].split("&", 1)[0]

        callback_response = await client.get(
            f"/api/v1/auth/oidc/callback?state={state}&code=oidc-code-1",
            follow_redirects=False,
        )
        assert callback_response.status_code == 303
        assert callback_response.headers["location"] == "/admin/chat"

        set_cookie = "\n".join(callback_response.headers.get_list("set-cookie"))
        assert "access_token=" in set_cookie
        assert "refresh_token=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert "Path=/api/v1/auth" in set_cookie

        user = (await db.execute(select(User).where(User.username == "oidc-user"))).scalar_one()
        identity = (
            await db.execute(
                select(UserIdentity).where(
                    UserIdentity.provider_id == provider.id,
                    UserIdentity.user_id == user.id,
                )
            )
        ).scalar_one()
        assert identity.subject == "user-sub-123"

        refresh_rows = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))).scalars().all()
        assert refresh_rows
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_refresh_cookie_requires_same_origin_headers(client, db, monkeypatch, auth_user):
    async def fake_refresh_access_token(_db, refresh_token: str):
        assert refresh_token == "cookie-refresh-token"
        # The refresh contract returns the rotated token's user; the route audits it.
        return {
            "user": auth_user,
            "access_token": "access-token-2",
            "refresh_token": "refresh-token-2",
        }

    monkeypatch.setattr(api_auth_module, "refresh_access_token", fake_refresh_access_token)
    client.cookies.set("refresh_token", "cookie-refresh-token", path="/api/v1/auth")

    blocked_response = await send_without_origin(client, "POST", "/api/v1/auth/refresh")
    assert blocked_response.status_code == 403
    assert blocked_response.json()["detail"] in {
        "Cross-site request blocked",
        "Missing same-origin browser headers",
    }

    allowed_response = await client.post("/api/v1/auth/refresh", headers={"Origin": "http://test"})
    assert allowed_response.status_code == 200
    payload = allowed_response.json()
    assert payload["access_token"] == "access-token-2"
    assert payload["refresh_token"] == "refresh-token-2"


@pytest.mark.asyncio
async def test_cookie_authenticated_auth_mutation_requires_same_origin_headers(client, db, auth_user):
    client.cookies.set("access_token", create_access_token(auth_user.id), path="/")

    blocked_response = await send_without_origin(
        client,
        "POST",
        "/api/v1/auth/me/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "updated-password-1"},
    )
    assert blocked_response.status_code == 403
    assert blocked_response.json()["detail"] in {
        "Cross-site request blocked",
        "Missing same-origin browser headers",
    }

    allowed_response = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "updated-password-1"},
        headers={"Origin": "http://test"},
    )
    assert allowed_response.status_code == 200
    assert allowed_response.json()["message"] == "Password updated successfully"


@pytest.mark.asyncio
async def test_bearer_authenticated_auth_mutation_skips_cookie_same_origin_guard(client, auth_headers, db, auth_user):
    client.cookies.set("access_token", create_access_token(auth_user.id), path="/")

    response = await client.put(
        "/api/v1/auth/me",
        json={"display_name": "Bearer Update"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Bearer Update"


@pytest.mark.asyncio
async def test_admin_login_blocks_cross_site_origin(client):
    response = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site request blocked"


@pytest.mark.asyncio
async def test_admin_logout_blocks_cross_site_referer(client):
    login_response = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": "http://test"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    # No ``Origin``: the Referer is the only evidence left, which is the case
    # this test is about.
    response = await send_without_origin(
        client,
        "GET",
        "/admin/logout",
        headers={"Referer": "https://evil.example/attack"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site request blocked"
