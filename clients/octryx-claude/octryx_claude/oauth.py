"""``octryx-claude login``: OAuth 2.1 authorization code + PKCE S256 against the platform.

The user signs in and consents in their own browser; the CLI never sees a password.
A public client (``token_endpoint_auth_method: none``) is registered with one loopback
redirect (RFC 8252) served by a one-shot local HTTP server. The client id and its
port are kept, so a later login reuses them when the port is free again.

``--headless`` is a dev-only path for automated acceptance: it signs in with
``OCTRYX_USERNAME`` / ``OCTRYX_PASSWORD`` from the environment (never printed) and approves
the consent over HTTP.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import os
import secrets
import time
import webbrowser
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .platform import safe_code
from .state import LocalState
from .tokens import GATEWAY_AUDIENCE, TokenUnavailableError, request_token, store_token_response

CLIENT_NAME = "octryx-claude"
# workflow:* and sessions:read: governed workflow contracts, confirmations and approval/run status over MCP.
# ``work:manage``: the agent board, work-item claims and handoffs (seat finding SL-1).
SCOPES = ("model:invoke knowledge:read knowledge:write session:write workflow:read workflow:execute sessions:read "
          "work:manage")
CALLBACK_PATH = "/callback"
LOGIN_TIMEOUT_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 15.0


class LoginError(Exception):
    """Login could not complete. ``code`` is a fixed reason, safe to print."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def authorize_url(base_url: str, *, client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "resource": GATEWAY_AUDIENCE,
        }
    )
    return f"{base_url}/oauth/authorize?{query}"


def register_client(http: httpx.Client, base_url: str, redirect_uri: str) -> str:
    try:
        response = http.post(
            f"{base_url}/oauth/register",
            json={
                "client_name": CLIENT_NAME,
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": SCOPES,
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise LoginError("platform_unreachable") from exc
    if response.status_code != 201:
        raise LoginError("client_registration_failed")
    try:
        client_id = str((response.json() or {}).get("client_id") or "")
    except (ValueError, AttributeError) as exc:
        raise LoginError("client_registration_failed") from exc
    if not client_id:
        raise LoginError("client_registration_failed")
    return client_id


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        self.server.callback_query = {k: v[0] for k, v in parse_qs(parsed.query).items()}  # type: ignore[attr-defined]
        body = b"Octryx login finished. You can close this window and return to the terminal.\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return  # the query carries the authorization code; never log it


def _bind_callback_server(preferred_port: int) -> http.server.HTTPServer:
    for port in (preferred_port, 0) if preferred_port else (0,):
        try:
            server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
        except OSError:
            continue
        server.callback_query = None  # type: ignore[attr-defined]
        return server
    raise LoginError("callback_port_unavailable")


def _await_callback(server: http.server.HTTPServer) -> dict[str, str]:
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    server.timeout = 1.0
    while server.callback_query is None:  # type: ignore[attr-defined]
        if time.monotonic() > deadline:
            raise LoginError("login_timed_out")
        server.handle_request()
    return server.callback_query  # type: ignore[attr-defined]


def _client_for(http: httpx.Client, credentials: dict[str, Any], base_url: str, port: int) -> str:
    """Reuse the stored client when it was registered for this base URL and port."""
    redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
    if credentials.get("base_url") == base_url and credentials.get("redirect_uri") == redirect_uri:
        client_id = str(credentials.get("client_id") or "")
        if client_id:
            return client_id
    return register_client(http, base_url, redirect_uri)


def _exchange(
    http: httpx.Client, base_url: str, *, client_id: str, code: str, redirect_uri: str, verifier: str
) -> dict[str, Any]:
    try:
        return request_token(
            http,
            base_url=base_url,
            form={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": GATEWAY_AUDIENCE,
            },
        )
    except TokenUnavailableError as exc:
        raise LoginError(f"code_exchange_{exc.code}") from exc


def _save(state: LocalState, base_url: str, client_id: str, redirect_uri: str, payload: dict[str, Any]) -> None:
    granted = set(str(payload.get("scope") or "").split())
    if "model:invoke" not in granted:
        raise LoginError("scope_model_invoke_missing")
    with state.credentials_lock():
        # ``store_token_response`` also records the granted scopes (seat finding SL-1).
        credentials: dict[str, Any] = {"base_url": base_url, "client_id": client_id, "redirect_uri": redirect_uri}
        store_token_response(credentials, payload, audience=GATEWAY_AUDIENCE, now=time.time())
        state.write_credentials(credentials)


def interactive_login(
    state: LocalState,
    base_url: str,
    *,
    http: httpx.Client,
    open_browser: Callable[[str], bool] = webbrowser.open,
    announce: Callable[[str], None] = print,
) -> None:
    credentials = state.credentials()
    stored = urlparse(str(credentials.get("redirect_uri") or ""))
    preferred_port = stored.port if credentials.get("base_url") == base_url and stored.port else 0
    server = _bind_callback_server(preferred_port or 0)
    try:
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
        client_id = _client_for(http, credentials, base_url, port)
        verifier, challenge = pkce_pair()
        expected_state = secrets.token_urlsafe(24)
        url = authorize_url(
            base_url, client_id=client_id, redirect_uri=redirect_uri, challenge=challenge, state=expected_state
        )
        announce("Opening the browser for the Octryx sign-in. If it does not open, visit:")
        announce(url)
        open_browser(url)
        query = _await_callback(server)
    finally:
        server.server_close()
    if query.get("error"):
        raise LoginError(safe_code(query.get("error")) or "authorization_failed")
    if not secrets.compare_digest(str(query.get("state") or ""), expected_state):
        raise LoginError("state_mismatch")
    code = str(query.get("code") or "")
    if not code:
        raise LoginError("authorization_code_missing")
    payload = _exchange(http, base_url, client_id=client_id, code=code, redirect_uri=redirect_uri, verifier=verifier)
    _save(state, base_url, client_id, redirect_uri, payload)


def headless_login(state: LocalState, base_url: str, *, http: httpx.Client) -> None:
    """Dev-only: platform login from OCTRYX_USERNAME / OCTRYX_PASSWORD, consent over HTTP."""
    username = os.environ.get("OCTRYX_USERNAME", "")
    password = os.environ.get("OCTRYX_PASSWORD", "")
    if not username or not password:
        raise LoginError("headless_credentials_missing")
    redirect_uri = f"http://127.0.0.1:45456{CALLBACK_PATH}"  # never served: the code is read from Location
    try:
        login = http.post(
            f"{base_url}/api/v1/auth/login",
            data={"username": username, "password": password},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        if login.status_code != 200:
            raise LoginError("headless_platform_login_failed")
        try:
            platform_jwt = str((login.json() or {}).get("access_token") or "")
        except (ValueError, AttributeError) as exc:
            raise LoginError("headless_platform_login_failed") from exc
        client_id = _client_for(http, state.credentials(), base_url, 45456)
        verifier, challenge = pkce_pair()
        expected_state = secrets.token_urlsafe(24)
        headers = {
            "Authorization": f"Bearer {platform_jwt}",
            "Origin": base_url,
            "Referer": f"{base_url}/oauth/authorize",
        }
        url = authorize_url(
            base_url, client_id=client_id, redirect_uri=redirect_uri, challenge=challenge, state=expected_state
        )
        response = http.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False)
        if response.status_code == 200:
            response = http.post(
                f"{base_url}/oauth/authorize/decision",
                data={
                    "decision": "approve",
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "scope": SCOPES,
                    "state": expected_state,
                    "code_challenge": challenge,
                    "resource": GATEWAY_AUDIENCE,
                },
                headers=headers,
                timeout=HTTP_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
    except httpx.HTTPError as exc:
        raise LoginError("platform_unreachable") from exc
    location = str(response.headers.get("location") or "")
    query = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
    if response.status_code not in (302, 303, 307) or not query.get("code"):
        raise LoginError("headless_consent_failed")
    if not secrets.compare_digest(str(query.get("state") or ""), expected_state):
        raise LoginError("state_mismatch")
    payload = _exchange(
        http, base_url, client_id=client_id, code=query["code"], redirect_uri=redirect_uri, verifier=verifier
    )
    _save(state, base_url, client_id, redirect_uri, payload)
