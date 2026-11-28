"""Real login, logout and refresh responses emit auth cookies whose Secure, SameSite and Path attributes follow the cookie policy."""

import pytest
from httpx import ASGITransport, AsyncClient

import app.auth_cookie_policy as policy_module
from app.auth_cookie_policy import ACCESS_TOKEN_COOKIE_MAX_AGE, REFRESH_TOKEN_COOKIE_MAX_AGE
from app.config import Settings
from app.main import app
from tests.conftest import ADMIN_PASSWORD
from tests.platform.auth_cookie_policy_support import (
    _cookie_attributes,
    _cookie_headers,
    _forced_secure_settings,
    _is_secure,
    _local_debug_settings,
    _settings,
)


def _forced_secure_debug_settings(**overrides) -> Settings:
    return _settings(debug=True, force_secure_auth_cookies=True, **overrides)


async def _login_response(client: AsyncClient, origin: str = "http://test"):
    return await client.post(
        "/chat/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": origin},
    )


@pytest.mark.asyncio
async def test_web_login_emits_non_secure_cookies_in_local_debug_mode(client, monkeypatch):
    monkeypatch.setattr(policy_module, "get_settings", _local_debug_settings)

    response = await _login_response(client)

    assert response.status_code == 303
    cookies = _cookie_headers(response)
    access, refresh = cookies["access_token"], cookies["refresh_token"]
    assert _is_secure(access) is False
    assert _is_secure(refresh) is False
    access_attributes, refresh_attributes = _cookie_attributes(access), _cookie_attributes(refresh)
    assert "httponly" in access_attributes and "httponly" in refresh_attributes
    assert access_attributes["samesite"] == refresh_attributes["samesite"] == "lax"
    assert access_attributes["max-age"] == str(ACCESS_TOKEN_COOKIE_MAX_AGE)
    assert refresh_attributes["max-age"] == str(REFRESH_TOKEN_COOKIE_MAX_AGE)
    assert access_attributes["path"] == "/"
    assert refresh_attributes["path"] == "/api/v1/auth"


@pytest.mark.asyncio
async def test_web_login_emits_secure_cookies_when_forced(client, monkeypatch):
    monkeypatch.setattr(policy_module, "get_settings", _forced_secure_settings)

    response = await _login_response(client)

    assert response.status_code == 303
    cookies = _cookie_headers(response)
    access, refresh = cookies["access_token"], cookies["refresh_token"]
    assert _is_secure(access) is True
    assert _is_secure(refresh) is True
    # Forcing Secure must not change any other cookie attribute.
    access_attributes, refresh_attributes = _cookie_attributes(access), _cookie_attributes(refresh)
    assert "httponly" in access_attributes and "httponly" in refresh_attributes
    assert access_attributes["samesite"] == refresh_attributes["samesite"] == "lax"
    assert access_attributes["max-age"] == str(ACCESS_TOKEN_COOKIE_MAX_AGE)
    assert refresh_attributes["max-age"] == str(REFRESH_TOKEN_COOKIE_MAX_AGE)
    assert access_attributes["path"] == "/"
    assert refresh_attributes["path"] == "/api/v1/auth"


@pytest.mark.asyncio
async def test_web_login_forced_secure_overrides_local_debug_loopback(client, monkeypatch):
    monkeypatch.setattr(policy_module, "get_settings", _forced_secure_debug_settings)

    response = await _login_response(client)

    assert response.status_code == 303
    cookies = _cookie_headers(response)
    assert _is_secure(cookies["access_token"]) is True
    assert _is_secure(cookies["refresh_token"]) is True


@pytest.mark.asyncio
async def test_web_login_over_https_emits_secure_cookies_in_local_debug_mode(client, monkeypatch):
    # The `client` fixture installs the test database overrides; this test only
    # needs a second client speaking HTTPS to the same app.
    monkeypatch.setattr(policy_module, "get_settings", _local_debug_settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as https_client:
        response = await _login_response(https_client, origin="https://test")

    assert response.status_code == 303
    cookies = _cookie_headers(response)
    assert _is_secure(cookies["access_token"]) is True
    assert _is_secure(cookies["refresh_token"]) is True


@pytest.mark.asyncio
async def test_web_logout_clears_cookies_with_forced_secure_policy(client, monkeypatch):
    monkeypatch.setattr(policy_module, "get_settings", _forced_secure_settings)

    response = await client.get("/chat/logout", headers={"Referer": "http://test/chat"})

    assert response.status_code == 303
    cookies = _cookie_headers(response)
    assert set(cookies) == {"access_token", "refresh_token"}
    for raw in cookies.values():
        assert _is_secure(raw) is True
        assert _cookie_attributes(raw)["max-age"] == "0"
    assert _cookie_attributes(cookies["refresh_token"])["path"] == "/api/v1/auth"


@pytest.mark.asyncio
async def test_api_logout_clears_cookies_with_forced_secure_policy(client, monkeypatch):
    monkeypatch.setattr(policy_module, "get_settings", _forced_secure_settings)

    response = await client.post("/api/v1/auth/logout", json={})

    assert response.status_code == 200
    cookies = _cookie_headers(response)
    assert set(cookies) == {"access_token", "refresh_token"}
    for raw in cookies.values():
        assert _is_secure(raw) is True
        assert _cookie_attributes(raw)["max-age"] == "0"


@pytest.mark.asyncio
async def test_api_refresh_emits_no_auth_cookies(client, monkeypatch):
    monkeypatch.setattr(policy_module, "get_settings", _forced_secure_settings)

    login = await client.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 200
    assert _cookie_headers(login) == {}

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login.json()["refresh_token"]},
    )

    assert response.status_code == 200
    assert _cookie_headers(response) == {}
