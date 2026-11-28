"""Access tokens for the gateway and the knowledge MCP, from one rotating refresh token.
Each audience needs its own access token, minted through a refresh with the matching ``resource``."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import httpx

from .state import LocalState

GATEWAY_AUDIENCE = "octryx-model-gateway"
# Set only by the epic-delivery Stop replay's second attempt (``plain_driver.replay_stop``): fetch a fresh token instead
# of the cached one, so a token the platform no longer takes cannot fail the replay twice.
FORCE_REFRESH_ENV = "OCTRYX_FORCE_TOKEN_REFRESH"
MCP_AUDIENCE = "octryx-mcp"
# The device channel: 15-minute tokens, refreshed five minutes before expiry without a reconnect, so a
# failed refresh is retried several times (every 30 s) before the platform closes the channel.
DEVICE_AUDIENCE = "octryx-device"
DEVICE_REFRESH_SKEW_SECONDS = 5 * 60
# Refresh this long before expiry. It must exceed the apiKeyHelper cache lifetime the
# launcher configures, so a token Claude Code caches never expires inside the cache.
REFRESH_SKEW_SECONDS = 15 * 60
TOKEN_TIMEOUT_SECONDS = 10.0


class TokenUnavailableError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def request_token(
    http: httpx.Client,
    *,
    base_url: str,
    form: dict[str, str],
) -> dict[str, Any]:
    try:
        response = http.post(f"{base_url}/oauth/token", data=form, timeout=TOKEN_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise TokenUnavailableError("platform_unreachable") from exc
    if response.status_code in (400, 401):
        raise TokenUnavailableError("refresh_rejected")
    if response.status_code != 200:
        raise TokenUnavailableError("token_endpoint_error")
    try:
        payload = response.json()
    except ValueError as exc:
        raise TokenUnavailableError("invalid_token_response") from exc
    if not isinstance(payload, dict):
        raise TokenUnavailableError("invalid_token_response")
    if not str(payload.get("access_token") or "") or not str(payload.get("refresh_token") or ""):
        raise TokenUnavailableError("invalid_token_response")
    return payload


def store_token_response(
    credentials: dict[str, Any],
    payload: dict[str, Any],
    *,
    audience: str,
    now: float,
) -> str:
    access_token = str(payload["access_token"])
    try:
        expires_in = max(0, int(payload.get("expires_in") or 0))
    except (TypeError, ValueError):
        expires_in = 0
    credentials["refresh_token"] = str(payload["refresh_token"])
    if isinstance(payload.get("scope"), str) and payload["scope"].strip():
        credentials["scopes"] = sorted(set(payload["scope"].split()))  # what the grant allows
    tokens = credentials.get("tokens") if isinstance(credentials.get("tokens"), dict) else {}
    tokens[audience] = {"access_token": access_token, "expires_at": now + expires_in}
    credentials["tokens"] = tokens
    return access_token


def _cached(credentials: dict[str, Any], audience: str, now: float) -> str:
    tokens = credentials.get("tokens")
    entry = tokens.get(audience) if isinstance(tokens, dict) else None
    if not isinstance(entry, dict):
        return ""
    token = str(entry.get("access_token") or "")
    try:
        expires_at = float(entry.get("expires_at") or 0)
    except (TypeError, ValueError):
        return ""
    skew = DEVICE_REFRESH_SKEW_SECONDS if audience == DEVICE_AUDIENCE else REFRESH_SKEW_SECONDS
    if token and expires_at - now > skew:
        return token
    return ""


def get_access_token(
    state: LocalState,
    audience: str,
    *,
    http: httpx.Client,
    clock: Callable[[], float] = time.time,
) -> str:
    from . import token_broker  # noqa: PLC0415

    # An account that may not hold the credential (a server runner's agent) asks the launcher instead.
    if broker := token_broker.broker_path():
        return token_broker.request_token(audience, broker)
    with state.credentials_lock():
        credentials = state.credentials()
        base_url = str(credentials.get("base_url") or "")
        client_id = str(credentials.get("client_id") or "")
        refresh_token = str(credentials.get("refresh_token") or "")
        if not base_url or not client_id or not refresh_token:
            raise TokenUnavailableError("not_logged_in")
        now = clock()
        cached = "" if os.environ.get(FORCE_REFRESH_ENV) == "1" else _cached(credentials, audience, now)
        if cached:
            return cached
        payload = request_token(
            http,
            base_url=base_url,
            form={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "resource": audience,
            },
        )
        access_token = store_token_response(credentials, payload, audience=audience, now=now)
        state.write_credentials(credentials)
        return access_token
