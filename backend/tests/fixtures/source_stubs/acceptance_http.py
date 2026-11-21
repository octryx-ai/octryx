"""A small stdlib HTTP client for acceptance checks against the local stack (loopback only).

- Refuses any base URL that is not loopback, so a check that creates users and Workspaces can
  never be pointed at a shared deployment.
- Never follows redirects, so an OAuth ``code`` or a 303 target is read from the ``Location``
  header rather than fetched.
- Returns status codes and parsed JSON only. No response body, header value, token or password is
  printed by this module; callers print fixed facts.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import pathlib
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

SECRETS_FILE = pathlib.Path.home() / ".octryx/acceptance/secrets.env"
_RATE_LIMIT_RETRIES = 6
_MAX_RATE_LIMIT_WAIT_SECONDS = 65
MCP_RESOURCE = "octryx-mcp"
MCP_SCOPE = "knowledge:read"
# A redirect target nothing listens on: the code is read from the Location header, never fetched.
OAUTH_REDIRECT_URI = "http://127.0.0.1:53682/callback"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003 - urllib's signature
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def read_secret(name: str, path: pathlib.Path = SECRETS_FILE) -> str:
    """One value of the acceptance ``secrets.env``; the value is returned, never printed."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit(f"{name} is not in {path}")


def require_loopback(base_url: str) -> str:
    parts = urllib.parse.urlsplit(base_url)
    host = parts.hostname or ""
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if parts.scheme != "http" or not loopback:
        raise SystemExit("the acceptance base URL must be http on loopback (localhost or 127.0.0.1)")
    return f"{parts.scheme}://{parts.netloc}"


@dataclass
class Response:
    status: int
    payload: Any
    location: str


class AcceptanceClient:
    """Requests against one loopback stack; the Origin header is the stack's own origin."""

    def __init__(self, base_url: str) -> None:
        self.base = require_loopback(base_url)

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: Any = None,
        form: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> Response:
        sent = {"Origin": self.base, "Accept": "application/json", **(headers or {})}
        if token:
            sent["Authorization"] = f"Bearer {token}"
        data = None
        if json_body is not None:
            data, sent["Content-Type"] = json.dumps(json_body).encode(), "application/json"
        elif form is not None:
            data = urllib.parse.urlencode(form).encode()
            sent["Content-Type"] = "application/x-www-form-urlencoded"
        for _ in range(_RATE_LIMIT_RETRIES + 1):
            request = urllib.request.Request(self.base + path, data=data, headers=sent, method=method)
            try:
                with _OPENER.open(request, timeout=timeout) as response:
                    return Response(response.status, _json(response.read()), response.headers.get("Location") or "")
            except urllib.error.HTTPError as error:
                if error.code != 429:
                    return Response(error.code, _json(error.read()), error.headers.get("Location") or "")
                # The per-IP API limiter (30 writes a minute): wait as told, then send the same request.
                wait = min(_MAX_RATE_LIMIT_WAIT_SECONDS, max(1, _int(error.headers.get("Retry-After"))))
                sys.stderr.write(f"... rate limited, waiting {wait} s\n")
                time.sleep(wait + 0.5)
            except urllib.error.URLError:
                return Response(0, None, "")
        return Response(429, None, "")

    def login(self, username: str, password: str) -> str | None:
        answer = self.request("POST", "/api/v1/auth/login", form={"username": username, "password": password})
        if answer.status != 200 or not isinstance(answer.payload, dict):
            return None
        return answer.payload.get("access_token")

    def register_mcp_client(self, name: str, scope: str = MCP_SCOPE) -> str | None:
        answer = self.request(
            "POST",
            "/oauth/register",
            json_body={
                "client_name": name,
                "redirect_uris": [OAUTH_REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "none",
                "scope": scope,
            },
        )
        return answer.payload.get("client_id") if answer.status == 201 and isinstance(answer.payload, dict) else None

    def mcp_token(
        self, client_id: str, login_token: str, scope: str = MCP_SCOPE, resource: str = MCP_RESOURCE
    ) -> str | None:
        """An OAuth 2.1 access token (PKCE, resource indicator) for the logged-in user, or ``None``."""
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        query = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": scope,
            "state": "acl-check",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": resource,
        }
        answer = self.request("GET", "/oauth/authorize?" + urllib.parse.urlencode(query), token=login_token)
        location = answer.location
        if answer.status == 200:
            decision = {
                "decision": "approve",
                "client_id": client_id,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "scope": scope,
                "state": "acl-check",
                "code_challenge": challenge,
                "resource": resource,
            }
            location = self.request("POST", "/oauth/authorize/decision", token=login_token, form=decision).location
        code = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query).get("code", [None])[0]
        if not code:
            return None
        answer = self.request(
            "POST",
            "/oauth/token",
            form={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": resource,
            },
        )
        return answer.payload.get("access_token") if answer.status == 200 and isinstance(answer.payload, dict) else None

    def revoke(self, client_id: str, access_token: str) -> None:
        self.request("POST", "/oauth/revoke", form={"token": access_token, "client_id": client_id})

    def mcp_tool(
        self, access_token: str, workspace_id: str, tool: str, arguments: dict, headers: dict | None = None
    ) -> dict:
        """The governed tool's result (``state`` plus payload), or ``{"state": "http_<status>"}``."""
        answer = self.request(
            "POST",
            f"/api/v1/mcp/knowledge/tools/{tool}",
            token=access_token,
            json_body={"arguments": arguments},
            headers={"X-Octryx-Workspace": workspace_id, **(headers or {})},
        )
        if answer.status != 200 or not isinstance(answer.payload, dict):
            return {"state": f"http_{answer.status}"}
        result = answer.payload.get("result")
        return result if isinstance(result, dict) else {"state": "malformed"}

    def native_mcp_tool(self, access_token: str, workspace_id: str, tool: str, arguments: dict) -> dict:
        """Call the native protocol; the HTTP convenience endpoint cannot redeem confirmation tickets."""
        path = "/api/v1/mcp/knowledge-protocol/mcp"
        headers = {"X-Octryx-Workspace": workspace_id, "Accept": "application/json, text/event-stream"}
        initialized = self.request("POST", path, token=access_token, headers=headers, json_body={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "acceptance", "version": "1"},
            },
        })
        if initialized.status != 200:
            return {"state": f"http_{initialized.status}"}
        self.request("POST", path, token=access_token, headers=headers,
                     json_body={"jsonrpc": "2.0", "method": "notifications/initialized"})
        answer = self.request("POST", path, token=access_token, headers=headers, json_body={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": arguments},
        })
        if answer.status != 200 or not isinstance(answer.payload, dict):
            return {"state": f"http_{answer.status}"}
        result = answer.payload.get("result") or {}
        return result.get("structuredContent") or {"state": "protocol_error"}


def _int(raw: object) -> int:
    try:
        return int(str(raw))
    except ValueError:
        return _MAX_RATE_LIMIT_WAIT_SECONDS


def _json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
