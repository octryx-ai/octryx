"""OAuth 2.1 authorization-server tests: registration, code+PKCE flow,
refresh rotation, revocation, and platform-login-session binding."""

from __future__ import annotations

import pytest

from app.services.oauth_provider import verify_access_token
from tests.conftest import ADMIN_PASSWORD
from tests.support.oauth_provider_support import (
    _approve_consent,
    _authorize_params,
    _login_cookies,
    _pkce_pair,
    _register_client,
)


@pytest.mark.asyncio
async def test_metadata_document_lists_endpoints(client, db):
    response = await client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    body = response.json()
    assert body["authorization_endpoint"].endswith("/oauth/authorize")
    assert body["token_endpoint"].endswith("/oauth/token")
    assert body["registration_endpoint"].endswith("/oauth/register")
    assert body["code_challenge_methods_supported"] == ["S256"]


@pytest.mark.asyncio
async def test_dynamic_registration_public_client(client, db):
    registration = await _register_client(client)
    assert registration["client_id"].startswith("oec_")
    assert "client_secret" not in registration
    assert registration["token_endpoint_auth_method"] == "none"


@pytest.mark.asyncio
async def test_dynamic_registration_rejects_bad_redirect(client, db):
    response = await client.post(
        "/oauth/register",
        json={"client_name": "X", "redirect_uris": ["http://evil.example.com/cb"]},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


@pytest.mark.asyncio
async def test_authorize_requires_login_redirects_to_login_with_next(client, db):
    registration = await _register_client(client)
    _, challenge = _pkce_pair()
    response = await client.get(
        "/oauth/authorize", params=_authorize_params(registration, challenge)
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("/chat/login?next=")
    # Live (native Codex): the login keeps only a relative next; an absolute one sent the user to /chat instead.
    from urllib.parse import parse_qs, urlsplit

    next_path = parse_qs(urlsplit(location).query)["next"][0]
    assert next_path.startswith("/oauth/authorize?") and "client_id=" in next_path
    login = await client.post("/chat/login", data={"username": "admin", "password": ADMIN_PASSWORD,
                                                   "next": next_path}, headers={"Origin": "http://test"})
    assert login.status_code == 303 and login.headers["location"] == next_path


@pytest.mark.asyncio
async def test_full_code_flow_with_pkce_and_refresh_rotation(client, db):
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
    tokens = token_response.json()
    assert tokens["token_type"] == "Bearer"
    claims = verify_access_token(tokens["access_token"])
    assert claims is not None
    assert claims["client_id"] == registration["client_id"]
    assert "knowledge:read" in claims["scope"]

    # Code replay must fail.
    replay = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": registration["redirect_uris"][0],
            "code_verifier": verifier,
            "client_id": registration["client_id"],
        },
    )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"

    # Refresh rotation works and the old refresh token is dead afterwards.
    refresh1 = tokens["refresh_token"]
    refreshed = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh1,
            "client_id": registration["client_id"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    refresh2 = refreshed.json()["refresh_token"]
    assert refresh2 != refresh1

    rotated_replay = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh1,
            "client_id": registration["client_id"],
        },
    )
    assert rotated_replay.status_code == 400

    # Replay revoked the grant, so the rotated token dies with it.
    after_replay = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh2,
            "client_id": registration["client_id"],
        },
    )
    assert after_replay.status_code == 400


@pytest.mark.asyncio
async def test_wrong_pkce_verifier_is_rejected(client, db):
    registration = await _register_client(client)
    _, challenge = _pkce_pair()
    await _login_cookies(client)
    code = await _approve_consent(client, registration, challenge)
    response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": registration["redirect_uris"][0],
            "code_verifier": "not-the-right-verifier-at-all-not-even-close",
            "client_id": registration["client_id"],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_redirect_uri_must_match_between_authorize_and_token(client, db):
    registration = await _register_client(
        client,
        redirect_uris=["http://localhost:33418/callback", "http://127.0.0.1:9999/alt"],
    )
    verifier, challenge = _pkce_pair()
    await _login_cookies(client)
    code = await _approve_consent(client, registration, challenge)
    response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://127.0.0.1:9999/alt",
            "code_verifier": verifier,
            "client_id": registration["client_id"],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
