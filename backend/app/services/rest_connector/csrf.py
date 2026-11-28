"""CSRF token fetch before a write (SAP Gateway / OData), as an option of the definition's auth."""

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
    pass


def normalize_csrf(raw: Any) -> dict[str, Any] | None:
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
    return response.status_code == 403 and str(response.headers.get(csrf["header"]) or "").lower() == REQUIRED


def session_values(client: httpx.AsyncClient, token: str) -> list[str]:
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
