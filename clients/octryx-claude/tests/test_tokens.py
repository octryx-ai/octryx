"""apiKeyHelper token logic: cache, rotation-safe refresh, explicit failure."""

from __future__ import annotations

import os
import stat
import time
from urllib.parse import parse_qs

import httpx
import pytest

from octryx_claude.tokens import (
    GATEWAY_AUDIENCE,
    MCP_AUDIENCE,
    REFRESH_SKEW_SECONDS,
    TokenUnavailableError,
    get_access_token,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_cached_token_is_returned_without_a_network_call(state):
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("no refresh expected")

    assert get_access_token(state, GATEWAY_AUDIENCE, http=_client(handler)) == "gw-cached"


def test_refresh_near_expiry_rotates_the_refresh_token_for_the_requested_audience(state):
    seen: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/token"
        seen.append(parse_qs(request.content.decode()))
        return httpx.Response(
            200, json={"access_token": "mcp-new", "refresh_token": "refresh-2", "expires_in": 86400}
        )

    token = get_access_token(state, MCP_AUDIENCE, http=_client(handler))

    assert token == "mcp-new"
    assert seen[0]["grant_type"] == ["refresh_token"]
    assert seen[0]["refresh_token"] == ["refresh-1"]
    assert seen[0]["resource"] == [MCP_AUDIENCE]
    stored = state.credentials()
    assert stored["refresh_token"] == "refresh-2"
    assert stored["tokens"][GATEWAY_AUDIENCE]["access_token"] == "gw-cached"
    assert stat.S_IMODE(os.stat(state.credentials_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(state.root).st_mode) == 0o700


def test_token_inside_the_skew_window_is_refreshed(state):
    credentials = state.credentials()
    credentials["tokens"][GATEWAY_AUDIENCE]["expires_at"] = time.time() + REFRESH_SKEW_SECONDS - 5
    state.write_credentials(credentials)

    def handler(request):
        return httpx.Response(200, json={"access_token": "gw-new", "refresh_token": "refresh-2", "expires_in": 60})

    assert get_access_token(state, GATEWAY_AUDIENCE, http=_client(handler)) == "gw-new"


def test_rejected_refresh_is_explicit_and_keeps_the_stored_credentials(state):
    state.write_credentials({**state.credentials(), "tokens": {}})

    def handler(request):
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "secret detail"})

    with pytest.raises(TokenUnavailableError) as caught:
        get_access_token(state, GATEWAY_AUDIENCE, http=_client(handler))
    assert caught.value.code == "refresh_rejected"
    assert state.credentials()["refresh_token"] == "refresh-1"


def test_missing_login_is_not_logged_in(state):
    state.write_credentials({})
    with pytest.raises(TokenUnavailableError) as caught:
        get_access_token(state, GATEWAY_AUDIENCE, http=_client(lambda request: httpx.Response(500)))
    assert caught.value.code == "not_logged_in"


def test_the_stop_replays_second_attempt_fetches_a_fresh_token(state, monkeypatch):
    """The epic-delivery Stop replay retries once with OCTRYX_FORCE_TOKEN_REFRESH=1: the cached token is not reused
    then."""
    from octryx_claude.tokens import FORCE_REFRESH_ENV

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "gw-fresh", "refresh_token": "refresh-2", "expires_in": 86400})

    monkeypatch.setenv(FORCE_REFRESH_ENV, "1")
    assert get_access_token(state, GATEWAY_AUDIENCE, http=_client(handler)) == "gw-fresh"
