"""Shared PKCE, client registration, login and consent helpers for the OAuth authorization-server tests."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

from tests.conftest import ADMIN_PASSWORD


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")
    return verifier, challenge


async def _register_client(client, **overrides) -> dict:
    payload = {
        "client_name": "Claude Code",
        "redirect_uris": ["http://localhost:33418/callback"],
        "scope": "knowledge:read tasks:read",
        **overrides,
    }
    response = await client.post("/oauth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _login_cookies(client) -> None:
    response = await client.post(
        "/chat/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": "http://test"},
    )
    assert response.status_code == 303, response.text


def _authorize_params(registration: dict, challenge: str, state: str = "xyz") -> dict:
    return {
        "response_type": "code",
        "client_id": registration["client_id"],
        "redirect_uri": registration["redirect_uris"][0],
        "scope": "knowledge:read tasks:read",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }


async def _approve_consent(client, registration: dict, challenge: str) -> str:
    """Run authorize + consent approval; return the authorization code."""
    authorize = await client.get("/oauth/authorize", params=_authorize_params(registration, challenge))
    if authorize.status_code == 302:
        location = authorize.headers["location"]
    else:
        assert authorize.status_code == 200, authorize.text
        decision = await client.post(
            "/oauth/authorize/decision",
            data={
                "decision": "approve",
                "client_id": registration["client_id"],
                "redirect_uri": registration["redirect_uris"][0],
                "scope": "knowledge:read tasks:read",
                "state": "xyz",
                "code_challenge": challenge,
                "resource": "",
            },
            headers={"Origin": "http://test"},
        )
        assert decision.status_code == 302, decision.text
        location = decision.headers["location"]
    parsed = parse_qs(urlparse(location).query)
    assert parsed.get("state") == ["xyz"]
    return parsed["code"][0]
