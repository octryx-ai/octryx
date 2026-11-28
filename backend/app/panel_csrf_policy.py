"""Same-origin policy for cookie-authenticated admin-panel mutations."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Request

from .auth_cookie_policy import ACCESS_TOKEN_COOKIE, PHONE_ACCESS_COOKIE
from .config import Settings, get_settings
from .http_security import (
    SAFE_HTTP_METHODS,
    current_request_origin,
    parse_cors_allowed_origins,
)

#: Every guarded path contains this marker, under any mount prefix.
PANEL_PATH_MARKER = "/chat/api/panel/"

#: Cookies that authenticate a browser on the panel surface.
PANEL_AUTH_COOKIES = (ACCESS_TOKEN_COOKIE, PHONE_ACCESS_COOKIE)

CSRF_REJECTION_STATUS = 403
CSRF_REJECTION_DETAIL = "Cross-site request blocked."

# Allow reasons.
REASON_SAFE_METHOD = "safe_method"
REASON_UNGUARDED_PATH = "unguarded_path"
#: No auth cookie, but a bearer token — the credential this surface falls back to
#: and the one a cross-site page cannot attach.
REASON_BEARER_CLIENT = "bearer_client"
#: No auth cookie and no bearer token: nothing this surface authenticates with,
#: so the route answers 401 on its own.
REASON_NO_AUTH_COOKIE = "no_auth_cookie"
REASON_EFFECTIVE_ORIGIN = "effective_request_origin"
REASON_CONFIGURED_ORIGIN = "configured_allowed_origin"

# Deny reasons.
REASON_FOREIGN_ORIGIN = "foreign_origin"
REASON_MISSING_ORIGIN = "missing_origin_evidence"

__all__ = [
    "CSRF_REJECTION_DETAIL",
    "CSRF_REJECTION_STATUS",
    "PANEL_AUTH_COOKIES",
    "PANEL_PATH_MARKER",
    "REASON_BEARER_CLIENT",
    "REASON_CONFIGURED_ORIGIN",
    "REASON_EFFECTIVE_ORIGIN",
    "REASON_FOREIGN_ORIGIN",
    "REASON_MISSING_ORIGIN",
    "REASON_NO_AUTH_COOKIE",
    "REASON_SAFE_METHOD",
    "REASON_UNGUARDED_PATH",
    "OriginDecision",
    "evaluate_panel_mutation",
    "expected_panel_origins",
    "is_guarded_panel_path",
]


@dataclass(frozen=True)
class OriginDecision:
    allowed: bool
    reason: str


def is_guarded_panel_path(path: str | None) -> bool:
    return PANEL_PATH_MARKER in str(path or "")


def _normalize_origin(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def _has_bearer_authorization(request: Request) -> bool:
    authorization = str(request.headers.get("authorization") or "").strip()
    scheme, _, token = authorization.partition(" ")
    return scheme.lower() == "bearer" and bool(token.strip())


def _has_panel_auth_cookie(request: Request) -> bool:
    return any(str(request.cookies.get(name) or "").strip() for name in PANEL_AUTH_COOKIES)


def _resolve_claimed_origin(request: Request) -> str:
    if "origin" in request.headers:
        return _normalize_origin(request.headers.get("origin"))
    return _normalize_origin(request.headers.get("referer"))


def expected_panel_origins(request: Request, settings: Settings | None = None) -> tuple[str, ...]:
    resolved = settings or get_settings()
    origins = [current_request_origin(request)]
    for origin in parse_cors_allowed_origins(resolved.cors_allowed_origins):
        if origin not in origins:
            origins.append(origin)
    return tuple(origin for origin in origins if origin)


def _decide_by_origin(request: Request, settings: Settings | None) -> OriginDecision:
    origin = _resolve_claimed_origin(request)
    if not origin:
        return OriginDecision(False, REASON_MISSING_ORIGIN)
    expected = expected_panel_origins(request, settings)
    if expected and origin == expected[0]:
        return OriginDecision(True, REASON_EFFECTIVE_ORIGIN)
    if origin in expected:
        return OriginDecision(True, REASON_CONFIGURED_ORIGIN)
    return OriginDecision(False, REASON_FOREIGN_ORIGIN)


def evaluate_panel_mutation(request: Request, settings: Settings | None = None) -> OriginDecision:
    if not is_guarded_panel_path(request.url.path):
        return OriginDecision(True, REASON_UNGUARDED_PATH)
    if request.method.upper() in SAFE_HTTP_METHODS:
        return OriginDecision(True, REASON_SAFE_METHOD)
    if _has_panel_auth_cookie(request):
        return _decide_by_origin(request, settings)
    if _has_bearer_authorization(request):
        return OriginDecision(True, REASON_BEARER_CLIENT)
    return OriginDecision(True, REASON_NO_AUTH_COOKIE)
