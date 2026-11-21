"""Contract: the OAuth server mints tokens only for known resource indicators (RFC 8707)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.mcp_knowledge_protocol import KNOWLEDGE_MCP_MOUNT_PATH, KNOWLEDGE_MCP_STREAMABLE_PATH
from app.services.oauth_provider import (
    acceptable_mcp_audiences,
    resolve_oauth_resource_context,
    verify_access_token,
)
from app.services.oauth_provider.tokens import DEFAULT_RESOURCE_AUDIENCE
from tests.oauth_test_utils import obtain_oauth_tokens, pkce_pair

UNKNOWN_RESOURCE = "https://attacker.example/api"


def _aud(token: str, audience: str) -> str | None:
    claims = verify_access_token(token, audience=audience)
    return None if claims is None else claims["aud"]


async def _refresh(client, tokens: dict, resource: str | None):
    data = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": tokens["client_id"]}
    if resource is not None:
        data["resource"] = resource
    return await client.post("/oauth/token", data=data)


@pytest.mark.asyncio
async def test_gateway_audience_on_code_and_refresh_and_mcp_default_when_absent(client, db):
    tokens = await obtain_oauth_tokens(client, scope=SCOPE_MODEL_INVOKE, resource=GATEWAY_AUDIENCE)
    assert _aud(tokens["access_token"], GATEWAY_AUDIENCE) == GATEWAY_AUDIENCE

    refreshed = await _refresh(client, tokens, GATEWAY_AUDIENCE)
    assert refreshed.status_code == 200, refreshed.text
    assert _aud(refreshed.json()["access_token"], GATEWAY_AUDIENCE) == GATEWAY_AUDIENCE

    absent = await _refresh(client, {**refreshed.json(), "client_id": tokens["client_id"]}, None)
    assert absent.status_code == 200, absent.text
    assert _aud(absent.json()["access_token"], DEFAULT_RESOURCE_AUDIENCE) == DEFAULT_RESOURCE_AUDIENCE


@pytest.mark.asyncio
async def test_unknown_resource_is_invalid_target_on_token_and_authorize(client, db):
    tokens = await obtain_oauth_tokens(client)

    refused = await _refresh(client, tokens, UNKNOWN_RESOURCE)
    assert refused.status_code == 400
    assert refused.json()["error"] == "invalid_target"
    assert UNKNOWN_RESOURCE not in refused.text
    # The refusal happens before the grant is touched: the refresh token still works.
    assert (await _refresh(client, tokens, None)).status_code == 200

    _, challenge = pkce_pair()
    authorize = await client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": tokens["client_id"],
            "redirect_uri": "http://localhost:33418/callback",
            "scope": "knowledge:read",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st1",
            "resource": UNKNOWN_RESOURCE,
        },
    )
    assert authorize.status_code == 302
    location = authorize.headers["location"]
    assert location.startswith("http://localhost:33418/callback?")
    query = parse_qs(urlparse(location).query)
    assert query["error"] == ["invalid_target"]
    assert query["state"] == ["st1"]
    assert "code" not in query
    assert "attacker.example" not in location


@pytest.mark.asyncio
async def test_advertised_mcp_resource_url_mints_a_token_the_mcp_verifier_accepts(client, db):
    metadata = (await client.get("/.well-known/oauth-protected-resource")).json()
    tokens = await obtain_oauth_tokens(client, resource=metadata["resource"])

    assert _aud(tokens["access_token"], DEFAULT_RESOURCE_AUDIENCE) == DEFAULT_RESOURCE_AUDIENCE
    audiences = acceptable_mcp_audiences(
        mount_path=KNOWLEDGE_MCP_MOUNT_PATH, streamable_path=KNOWLEDGE_MCP_STREAMABLE_PATH
    )
    context = await resolve_oauth_resource_context(db, token=tokens["access_token"], audiences=audiences)
    assert context is not None
