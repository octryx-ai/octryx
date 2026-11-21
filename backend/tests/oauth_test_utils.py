"""Shared helpers: obtain platform OAuth tokens in tests via the real flow."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

from tests.conftest import ADMIN_PASSWORD


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")
    return verifier, challenge


async def obtain_oauth_tokens(
    client,
    *,
    scope: str = "knowledge:read",
    username: str = "admin",
    password: str = ADMIN_PASSWORD,
    resource: str | None = None,
) -> dict:
    """Register a client, log in, consent, and exchange the code.

    Returns the token response dict plus ``client_id`` and ``grant`` info.
    """
    registration = await client.post(
        "/oauth/register",
        json={
            "client_name": "test-agent",
            "redirect_uris": ["http://localhost:33418/callback"],
            "scope": scope,
        },
    )
    assert registration.status_code == 201, registration.text
    reg = registration.json()

    login = await client.post(
        "/chat/login",
        data={"username": username, "password": password},
        headers={"Origin": "http://test"},
    )
    assert login.status_code == 303, login.text

    verifier, challenge = pkce_pair()
    params = {
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": reg["redirect_uris"][0],
        "scope": scope,
        "state": "s1",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if resource is not None:
        params["resource"] = resource
    authorize = await client.get("/oauth/authorize", params=params)
    if authorize.status_code == 302:
        location = authorize.headers["location"]
    else:
        assert authorize.status_code == 200, authorize.text
        decision = await client.post(
            "/oauth/authorize/decision",
            data={
                "decision": "approve",
                "client_id": reg["client_id"],
                "redirect_uri": reg["redirect_uris"][0],
                "scope": scope,
                "state": "s1",
                "code_challenge": challenge,
                "resource": resource or "",
            },
            headers={"Origin": "http://test"},
        )
        assert decision.status_code == 302, decision.text
        location = decision.headers["location"]
    code = parse_qs(urlparse(location).query)["code"][0]

    token_response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": reg["redirect_uris"][0],
            "code_verifier": verifier,
            "client_id": reg["client_id"],
        },
    )
    assert token_response.status_code == 200, token_response.text
    tokens = token_response.json()
    tokens["client_id"] = reg["client_id"]
    return tokens
