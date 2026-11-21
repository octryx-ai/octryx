"""ServiceNow OAuth with the password grant and its refresh token (mode ``oauth_password``).

The integration document of a ServiceNow instance can name its own OAuth: a form-encoded POST to the
admin-entered token URL (usually ``<instance>/oauth_token.do``) with ``grant_type=password``, ``client_id``,
``client_secret``, ``username`` and ``password``; the answer carries ``access_token``, ``refresh_token`` and
``expires_in``. Every value is admin-entered; nothing here names an instance, client or user.

The token handling follows ``oidc_client_credentials.py`` and reuses its URL rule and lifetime clamp:

- **Token URL:** ``https`` only (loopback ``http`` for tests), no userinfo; sent through the ServiceNow egress
  transport, never following a redirect (``oauth_token_endpoint_redirect``: the secrets are sent once).
- **Cache:** in process only, keyed by a hash over every credential value; it holds the access token, its expiry
  and the refresh token, never the password or the client secret. A token is used while more than 60 s remain.
  One request is in flight per key.
- **Refresh:** when a refresh token is cached, ``grant_type=refresh_token`` is tried first; when the instance
  refuses it (any 4xx), the password grant runs instead.
- **401 from the instance:** :class:`PasswordGrantBearerAuth` invalidates the token and retries once.
- **Errors:** :class:`OAuthPasswordError` with a closed code and a fixed message (``oauth_invalid_client``,
  ``oauth_invalid_grant`` for a wrong username or password, ``oauth_unauthorized_client``,
  ``oauth_token_endpoint_redirect``, ``oauth_bad_response``, plus the shared ``oidc_token_endpoint_unreachable``
  and ``oidc_token_url_invalid``). No secret, password or token is ever part of a message or log line.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import httpx

from .oidc_client_credentials import (
    CODE_TOKEN_ENDPOINT_UNREACHABLE,
    CODE_TOKEN_URL_INVALID,
    MAX_TOKEN_CHARS,
    REFRESH_MARGIN_SECONDS,
    OidcTokenError,
    token_url_problem,
)
from .oidc_client_credentials import (
    MESSAGES as OIDC_MESSAGES,
)
from .oidc_token_cache import _lifetime
from .outbound_egress import CONNECTION_SERVICENOW, EgressRefusedError, egress_transport

CODE_INVALID_CLIENT = "oauth_invalid_client"
CODE_INVALID_GRANT = "oauth_invalid_grant"
CODE_UNAUTHORIZED_CLIENT = "oauth_unauthorized_client"
CODE_REDIRECT = "oauth_token_endpoint_redirect"
CODE_BAD_RESPONSE = "oauth_bad_response"

MESSAGES = {
    CODE_INVALID_CLIENT: "ServiceNow refused the OAuth client id or client secret (invalid_client).",
    CODE_INVALID_GRANT: "ServiceNow refused the username or password of the integration user (invalid_grant).",
    CODE_UNAUTHORIZED_CLIENT: "ServiceNow does not allow this OAuth client the password grant (unauthorized_client).",
    CODE_REDIRECT: (
        "The token URL answered with a redirect; enter the final token URL. No credential was sent to the "
        "redirect target."
    ),
    CODE_BAD_RESPONSE: "ServiceNow answered without a usable access token.",
    CODE_TOKEN_ENDPOINT_UNREACHABLE: OIDC_MESSAGES[CODE_TOKEN_ENDPOINT_UNREACHABLE],
    CODE_TOKEN_URL_INVALID: OIDC_MESSAGES[CODE_TOKEN_URL_INVALID],
}
TOKEN_TIMEOUT_SECONDS = 15.0


class OAuthPasswordError(OidcTokenError):
    """A token could not be obtained; a closed code and a fixed message (never a value)."""

    def __init__(self, code: str, *, egress_refused: bool = False, http_status: int | None = None) -> None:
        Exception.__init__(self, f"{code}: {MESSAGES[code]}")
        self.code = code
        self.egress_refused = egress_refused
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class PasswordGrantCredentials:
    token_url: str
    client_id: str
    client_secret: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)
    scope: str | None = None

    def cache_key(self) -> str:
        values = (self.token_url, self.client_id, self.client_secret, self.username, self.password, self.scope or "")
        return hashlib.sha256("\x00".join(values).encode()).hexdigest()


@dataclass
class _Cached:
    access_token: str = field(repr=False)
    expires_at: float
    refresh_token: str | None = field(default=None, repr=False)


_cache: dict[str, _Cached] = {}
_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _now() -> float:
    return time.monotonic()


def clear_password_token_cache() -> None:
    _cache.clear()
    _locks.clear()


def _lock(key: str) -> asyncio.Lock:
    loop_key = (id(asyncio.get_running_loop()), key)
    lock = _locks.get(loop_key)
    if lock is None:
        lock = _locks[loop_key] = asyncio.Lock()
    return lock


def _fresh(key: str) -> str | None:
    cached = _cache.get(key)
    if cached is None or cached.expires_at - _now() <= REFRESH_MARGIN_SECONDS:
        return None
    return cached.access_token


def invalidate(credentials: PasswordGrantCredentials, token: str | None = None) -> None:
    """Expire the cached access token (only ``token`` when given); the refresh token stays usable."""
    cached = _cache.get(credentials.cache_key())
    if cached is not None and (token is None or cached.access_token == token):
        cached.expires_at = 0.0


def _error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    if error == "invalid_grant":
        return CODE_INVALID_GRANT
    if error == "unauthorized_client":
        return CODE_UNAUTHORIZED_CLIENT
    if error == "invalid_client" or response.status_code == 401:
        return CODE_INVALID_CLIENT
    if response.status_code >= 500:
        return CODE_TOKEN_ENDPOINT_UNREACHABLE
    return CODE_BAD_RESPONSE


def _usable(value: object) -> bool:
    return (
        type(value) is str and 0 < len(value) <= MAX_TOKEN_CHARS and value.isascii() and value.isprintable()
        and " " not in value
    )


def _parse(response: httpx.Response) -> _Cached:
    try:
        payload = response.json()
    except ValueError:
        raise OAuthPasswordError(CODE_BAD_RESPONSE) from None
    if not isinstance(payload, dict) or not _usable(payload.get("access_token")):
        raise OAuthPasswordError(CODE_BAD_RESPONSE)
    token_type = payload.get("token_type")
    if token_type is not None and str(token_type).lower() != "bearer":
        raise OAuthPasswordError(CODE_BAD_RESPONSE)
    refresh = payload.get("refresh_token")
    return _Cached(
        access_token=payload["access_token"],
        expires_at=_now() + _lifetime(payload.get("expires_in")),
        refresh_token=refresh if _usable(refresh) else None,
    )


async def _post(
    credentials: PasswordGrantCredentials, form: dict[str, str], transport: httpx.AsyncBaseTransport | None
) -> _Cached:
    if token_url_problem(credentials.token_url):
        raise OAuthPasswordError(CODE_TOKEN_URL_INVALID)
    pinned = egress_transport(CONNECTION_SERVICENOW, inner=transport)
    try:
        async with httpx.AsyncClient(transport=pinned, timeout=TOKEN_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.post(credentials.token_url, data=form, headers={"Accept": "application/json"})
    except EgressRefusedError:
        raise OAuthPasswordError(CODE_TOKEN_ENDPOINT_UNREACHABLE, egress_refused=True) from None
    except httpx.HTTPError:
        raise OAuthPasswordError(CODE_TOKEN_ENDPOINT_UNREACHABLE) from None
    if response.is_redirect or 300 <= response.status_code < 400:
        raise OAuthPasswordError(CODE_REDIRECT)
    if response.status_code != 200:
        raise OAuthPasswordError(_error_code(response), http_status=response.status_code)
    return _parse(response)


def _client_form(credentials: PasswordGrantCredentials) -> dict[str, str]:
    form = {"client_id": credentials.client_id, "client_secret": credentials.client_secret}
    if credentials.scope:
        form["scope"] = credentials.scope
    return form


async def _obtain(credentials: PasswordGrantCredentials, transport: httpx.AsyncBaseTransport | None) -> _Cached:
    cached = _cache.get(credentials.cache_key())
    if cached is not None and cached.refresh_token:
        refresh_form = {"grant_type": "refresh_token", "refresh_token": cached.refresh_token}
        try:
            renewed = await _post(credentials, {**refresh_form, **_client_form(credentials)}, transport)
        except OAuthPasswordError as error:
            if error.http_status is None or not 400 <= error.http_status < 500:
                raise  # unreachable, redirect or a bad answer: not a refused refresh token
        else:
            renewed.refresh_token = renewed.refresh_token or cached.refresh_token
            return renewed
    form = {"grant_type": "password", "username": credentials.username, "password": credentials.password}
    return await _post(credentials, {**form, **_client_form(credentials)}, transport)


async def access_token(
    credentials: PasswordGrantCredentials, *, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """A valid access token: the cached one, else refreshed, else a password grant (once per key at a time)."""
    key = credentials.cache_key()
    token = _fresh(key)
    if token is not None:
        return token
    async with _lock(key):
        token = _fresh(key)
        if token is not None:
            return token
        _cache[key] = await _obtain(credentials, transport)
        for idle in [entry for entry, lock in _locks.items() if not lock.locked()]:
            _locks.pop(idle, None)
        return _cache[key].access_token


class PasswordGrantBearerAuth(httpx.Auth):
    """``httpx`` auth of a ServiceNow client: the cached Bearer token, renewed and retried once on a 401."""

    requires_request_body = True

    def __init__(
        self, credentials: PasswordGrantCredentials, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._credentials = credentials
        self._transport = transport

    def __repr__(self) -> str:
        return "PasswordGrantBearerAuth()"

    def auth_flow(self, request: httpx.Request):  # noqa: ANN201 - sync clients are not supported
        raise RuntimeError("PasswordGrantBearerAuth needs an async client")

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
    "CODE_BAD_RESPONSE",
    "CODE_INVALID_CLIENT",
    "CODE_INVALID_GRANT",
    "CODE_REDIRECT",
    "CODE_UNAUTHORIZED_CLIENT",
    "MESSAGES",
    "OAuthPasswordError",
    "PasswordGrantBearerAuth",
    "PasswordGrantCredentials",
    "access_token",
    "clear_password_token_cache",
    "invalidate",
]
