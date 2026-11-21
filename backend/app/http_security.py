"""HTTP security helpers for auth cookies, CORS, and same-origin checks.

The ``Secure`` attribute of the auth cookies is not decided here: it comes from
``auth_cookie_policy``, which owns one authoritative policy for set and clear.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from .auth_cookie_policy import (
    ACCESS_TOKEN_COOKIE,
    ACCESS_TOKEN_COOKIE_MAX_AGE,
    REFRESH_TOKEN_COOKIE,
    REFRESH_TOKEN_COOKIE_MAX_AGE,
    AuthCookiePolicy,
    resolve_auth_cookie_policy,
)

__all__ = [
    "API_KEY_HEADER",
    "SAFE_HTTP_METHODS",
    "clear_auth_cookies",
    "current_request_origin",
    "get_auth_cookie_policy",
    "parse_cors_allowed_origins",
    "set_auth_cookies",
    "validate_same_origin_request",
]

SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Request header carrying a platform API key. Defined here, with the other
# transport-level security constants, so a policy that has to recognise a
# non-browser caller does not have to import the API-key service (and with it
# the ORM layer) to learn one header name. ``app.services.api_key`` stays the owner of
# everything the key itself means.
API_KEY_HEADER = "X-API-Key"


def _normalize_origin(origin: str | None) -> str:
    raw = str(origin or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def parse_cors_allowed_origins(raw: str | None) -> list[str]:
    values = []
    for item in str(raw or "").split(","):
        normalized = _normalize_origin(item)
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def current_request_origin(request: Request) -> str:
    return _normalize_origin(str(request.base_url).rstrip("/"))


def get_auth_cookie_policy(request: Request | None = None) -> AuthCookiePolicy:
    """Cookie attributes for this request, resolved by the auth-cookie policy."""
    return resolve_auth_cookie_policy(request)


def set_auth_cookies(
    response,
    *,
    access_token: str,
    refresh_token: str | None,
    request: Request | None = None,
) -> None:
    policy = get_auth_cookie_policy(request)
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        httponly=True,
        secure=policy.secure,
        samesite=policy.samesite,
        path=policy.access_token_path,
        max_age=ACCESS_TOKEN_COOKIE_MAX_AGE,
    )
    if refresh_token:
        response.set_cookie(
            REFRESH_TOKEN_COOKIE,
            refresh_token,
            httponly=True,
            secure=policy.secure,
            samesite=policy.samesite,
            path=policy.refresh_token_path,
            max_age=REFRESH_TOKEN_COOKIE_MAX_AGE,
        )


def clear_auth_cookies(response, *, request: Request | None = None) -> None:
    policy = get_auth_cookie_policy(request)
    response.delete_cookie(
        ACCESS_TOKEN_COOKIE,
        secure=policy.secure,
        samesite=policy.samesite,
        path=policy.access_token_path,
    )
    response.delete_cookie(
        REFRESH_TOKEN_COOKIE,
        secure=policy.secure,
        samesite=policy.samesite,
        path=policy.refresh_token_path,
    )


def validate_same_origin_request(request: Request) -> None:
    if request.method.upper() in SAFE_HTTP_METHODS:
        return

    expected_origin = current_request_origin(request)
    origin = _normalize_origin(request.headers.get("origin"))
    if origin:
        if origin != expected_origin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site request blocked")
        return

    referer = request.headers.get("referer")
    referer_origin = _normalize_origin(referer)
    if referer_origin and referer_origin == expected_origin:
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing same-origin browser headers")
