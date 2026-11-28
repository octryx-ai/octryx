"""The access token of an OpenID Connect client credentials client: fetched, cached in process, renewed on a 401."""

from __future__ import annotations

import asyncio
import base64
import math
import time
from collections.abc import AsyncGenerator
from urllib.parse import quote

import httpx

from ..outbound_egress import EgressRefusedError, egress_transport
from .oidc_client_credentials import (
    CLIENT_SECRET_BASIC,
    CODE_BAD_RESPONSE,
    CODE_INVALID_CLIENT,
    CODE_TOKEN_ENDPOINT_REDIRECT,
    CODE_TOKEN_ENDPOINT_UNREACHABLE,
    CODE_TOKEN_URL_INVALID,
    CODE_UNAUTHORIZED_CLIENT,
    DEFAULT_LIFETIME_SECONDS,
    MAX_LIFETIME_SECONDS,
    MAX_TOKEN_CHARS,
    REFRESH_MARGIN_SECONDS,
    TOKEN_TIMEOUT_SECONDS,
    OidcClientCredentials,
    OidcTokenError,
    token_url_problem,
)

# In process only; the key holds a digest of the secret, never the secret.
_tokens: dict[tuple[str, ...], tuple[str, float]] = {}
_locks: dict[tuple[int, tuple[str, ...]], asyncio.Lock] = {}


def _now() -> float:
    return time.monotonic()


def _fresh(key: tuple[str, ...]) -> str | None:
    cached = _tokens.get(key)
    if cached is None or cached[1] - _now() <= REFRESH_MARGIN_SECONDS:
        return None
    return cached[0]


def _lock(key: tuple[str, ...]) -> asyncio.Lock:
    loop_key = (id(asyncio.get_running_loop()), key)
    lock = _locks.get(loop_key)
    if lock is None:
        lock = _locks[loop_key] = asyncio.Lock()
    return lock


def _remember(key: tuple[str, ...], token: str, lifetime: float) -> None:
    now = _now()
    for stale in [entry for entry, (_token, expiry) in _tokens.items() if expiry <= now]:
        _tokens.pop(stale, None)
    _tokens[key] = (token, now + lifetime)
    # A free lock is safe to drop: a new one is created without an ``await`` in between (single flight holds).
    for idle in [entry for entry, lock in _locks.items() if not lock.locked()]:
        _locks.pop(idle, None)


def invalidate(credentials: OidcClientCredentials, token: str | None = None) -> None:
    # Only ``token`` when given, so a newer token of a concurrent refresh stays.
    key = credentials.cache_key()
    cached = _tokens.get(key)
    if cached is not None and (token is None or cached[0] == token):
        _tokens.pop(key, None)


def clear_token_cache() -> None:
    _tokens.clear()
    _locks.clear()


async def access_token(
    credentials: OidcClientCredentials, *, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    # Fetched once per key at a time.
    key = credentials.cache_key()
    token = _fresh(key)
    if token is not None:
        return token
    async with _lock(key):
        token = _fresh(key)
        if token is not None:
            return token
        token, lifetime = await _request_token(credentials, transport)
        _remember(key, token, lifetime)
        return token


def _token_request(credentials: OidcClientCredentials) -> tuple[dict[str, str], dict[str, str]]:
    form = {"grant_type": "client_credentials"}
    headers = {"Accept": "application/json"}
    if credentials.client_auth == CLIENT_SECRET_BASIC:
        pair = f"{quote(credentials.client_id, safe='')}:{quote(credentials.client_secret, safe='')}"
        headers["Authorization"] = f"Basic {base64.b64encode(pair.encode()).decode()}"
    else:
        form.update(client_id=credentials.client_id, client_secret=credentials.client_secret)
    if credentials.scope:
        form["scope"] = credentials.scope
    if credentials.audience:
        form["audience"] = credentials.audience
    return form, headers


def _error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    if response.status_code == 401 or error == "invalid_client":
        return CODE_INVALID_CLIENT
    if error == "unauthorized_client":
        return CODE_UNAUTHORIZED_CLIENT
    if response.status_code >= 500:
        return CODE_TOKEN_ENDPOINT_UNREACHABLE
    return CODE_BAD_RESPONSE


def _lifetime(value: object) -> float:
    if isinstance(value, bool):
        return DEFAULT_LIFETIME_SECONDS
    try:
        seconds = float(value) if isinstance(value, int | float | str) else 0.0
    except ValueError:
        return DEFAULT_LIFETIME_SECONDS
    if not math.isfinite(seconds) or seconds <= 0:  # NaN, infinity or none: the conservative default
        return DEFAULT_LIFETIME_SECONDS
    return min(seconds, MAX_LIFETIME_SECONDS)


def _parse_token(response: httpx.Response) -> tuple[str, float]:
    try:
        payload = response.json()
    except ValueError:
        raise OidcTokenError(CODE_BAD_RESPONSE) from None
    if not isinstance(payload, dict):
        raise OidcTokenError(CODE_BAD_RESPONSE)
    token, token_type = payload.get("access_token"), payload.get("token_type")
    usable = (
        type(token) is str and 0 < len(token) <= MAX_TOKEN_CHARS and token.isascii() and token.isprintable()
        and " " not in token
    )
    if not usable or (token_type is not None and str(token_type).lower() != "bearer"):
        raise OidcTokenError(CODE_BAD_RESPONSE)
    return token, _lifetime(payload.get("expires_in"))


async def _request_token(
    credentials: OidcClientCredentials, transport: httpx.AsyncBaseTransport | None
) -> tuple[str, float]:
    if token_url_problem(credentials.token_url):
        raise OidcTokenError(CODE_TOKEN_URL_INVALID)
    form, headers = _token_request(credentials)
    connection = credentials.connection  # a classified egress connection type of the connector
    pinned = egress_transport(connection, inner=transport)
    # No redirect is followed: the client secret would be sent to the redirect target.
    try:
        async with httpx.AsyncClient(
            transport=pinned, timeout=TOKEN_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            response = await client.post(credentials.token_url, data=form, headers=headers)
    except EgressRefusedError:
        raise OidcTokenError(CODE_TOKEN_ENDPOINT_UNREACHABLE, egress_refused=True) from None
    except httpx.HTTPError:
        raise OidcTokenError(CODE_TOKEN_ENDPOINT_UNREACHABLE) from None
    if response.is_redirect or 300 <= response.status_code < 400:
        raise OidcTokenError(CODE_TOKEN_ENDPOINT_REDIRECT)
    if response.status_code != 200:
        raise OidcTokenError(_error_code(response), http_status=response.status_code)
    return _parse_token(response)


class OidcBearerAuth(httpx.Auth):
    # Renewed and retried once on a 401.

    requires_request_body = True

    def __init__(
        self, credentials: OidcClientCredentials, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._credentials = credentials
        self._transport = transport

    def __repr__(self) -> str:
        return f"OidcBearerAuth(connection={self._credentials.connection!r})"

    def auth_flow(self, request: httpx.Request):  # noqa: ANN201 - sync clients are not supported
        raise RuntimeError("OidcBearerAuth needs an async client")

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        token = await access_token(self._credentials, transport=self._transport)
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code != 401:
            return
        invalidate(self._credentials, token)
        token = await access_token(self._credentials, transport=self._transport)
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


__all__ = [
    "OidcBearerAuth",
    "access_token",
    "clear_token_cache",
    "invalidate",
]
