"""CSRF token fetch before a write (SAP Gateway / OData), as an option of the definition's auth.

SAP Gateway refuses every modifying request (POST/PUT/PATCH/DELETE) with HTTP 403 and ``x-csrf-token: Required``
unless it carries a token fetched by a GET with ``x-csrf-token: Fetch`` *and* the session cookies of that GET. The
SAP Hub's Business Partner A2X spec, for example, has PATCH operations under ``/A_BusinessPartner(...)``.

``auth.csrf = {"fetch": true, "header": "x-csrf-token", "fetch_path": "/sap/opu/odata/sap/API_X/"}``; without
``fetch_path`` the service root (the connection's base URL) is fetched. The fetch runs in the SAME ``httpx`` client
as the write, so it goes through the same pinned egress transport, and the cookies it sets live only in that
client's jar: they reach the write and nothing else, never the tool result, the audit row or a log (the executor
adds token and cookie values to the values it redacts). On a 403 that says ``Required`` (the token expired between
fetch and write) the token is fetched once more and the write sent once more; never for any other answer.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from .common import READ_METHODS
from .http_call import send

DEFAULT_HEADER = "x-csrf-token"
FETCH = "Fetch"
REQUIRED = "required"


class CsrfFetchError(ValueError):
    """The token fetch did not return a token; the message names the status and header only."""


def normalize_csrf(raw: Any) -> dict[str, Any] | None:
    """The stored option, or ``None`` when off; a ``fetch_path`` is a path on the connection's host, never a URL."""
    if not isinstance(raw, dict) or not raw.get("fetch"):
        return None
    header = str(raw.get("header") or DEFAULT_HEADER).strip()
    if not header or header.lower() in {"authorization", "cookie", "host"}:
        raise HTTPException(status_code=400, detail="auth.csrf.header must name a token header")
    normalized: dict[str, Any] = {"fetch": True, "header": header}
    fetch_path = str(raw.get("fetch_path") or "").strip()
    if fetch_path:
        if not fetch_path.startswith("/") or "://" in fetch_path or fetch_path.startswith("//"):
            raise HTTPException(status_code=400, detail="auth.csrf.fetch_path must be a path starting with '/'")
        normalized["fetch_path"] = fetch_path
    return normalized


def csrf_for(auth: dict[str, Any] | None, method: str) -> dict[str, Any] | None:
    """The option when this call needs a token (a write with ``fetch`` on), else ``None``."""
    if str(method or "").upper() in READ_METHODS:
        return None
    raw = (auth or {}).get("csrf")
    return dict(raw) if isinstance(raw, dict) and raw.get("fetch") else None


def fetch_url(base_url: str, csrf: dict[str, Any]) -> str:
    if csrf.get("fetch_path"):
        return str(httpx.URL(base_url).copy_with(path=csrf["fetch_path"], query=None))
    return base_url.rstrip("/") + "/"


async def fetch_token(client: httpx.AsyncClient, *, base_url: str, csrf: dict[str, Any],
                      auth_headers: dict[str, str], auth_query: dict[str, str], timeout: float) -> str:
    """A fresh token; the session cookies of the answer stay in ``client``'s jar for the write."""
    header = csrf["header"]
    request = client.build_request("GET", fetch_url(base_url, csrf), params=auth_query or None,
                                   headers={"Accept": "application/json", **auth_headers, header: FETCH})
    response, _ = await send(client, request, timeout=timeout, retryable=True)
    await response.aread()
    token = str(response.headers.get(header) or "").strip()
    if response.status_code >= 400 or not token or token.lower() == REQUIRED:
        raise CsrfFetchError(f"The CSRF token fetch answered HTTP {response.status_code} without a '{header}' token.")
    return token


def token_required(response: httpx.Response, csrf: dict[str, Any]) -> bool:
    """The write was refused because the token is missing or expired (403 + ``<header>: Required``)."""
    return response.status_code == 403 and str(response.headers.get(csrf["header"]) or "").lower() == REQUIRED


def session_values(client: httpx.AsyncClient, token: str) -> list[str]:
    """Token and cookie values of the call, for the executor's redaction of error text."""
    return [token, *(cookie.value for cookie in client.cookies.jar if cookie.value)]


__all__ = [
    "DEFAULT_HEADER",
    "CsrfFetchError",
    "csrf_for",
    "fetch_token",
    "fetch_url",
    "normalize_csrf",
    "session_values",
    "token_required",
]
