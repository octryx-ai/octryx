"""Authoritative Secure-attribute policy for the auth cookies."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .config import (
    Settings,
    get_settings,
    is_production_like_runtime_profile,
)
from .trusted_proxy_policy import (
    FORWARDED_REQUEST_HEADERS,
    client_identity,
    parse_ip_address,
)

ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"
ACCESS_TOKEN_COOKIE_MAX_AGE = 86400
REFRESH_TOKEN_COOKIE_MAX_AGE = 86400 * 30
ACCESS_TOKEN_COOKIE_PATH = "/"
REFRESH_TOKEN_COOKIE_PATH = "/api/v1/auth"
#: The paired phone's own five-minute access cookie (Octryx Mobile ``/m``). Separate from the web login's
#: ``access_token`` so one browser can hold both: the phone never overwrites or clears the web login. Path ``/``
#: because the phone surfaces live under ``/api/v1`` and ``/chat/api``. It is only ever accepted as a phone token.
PHONE_ACCESS_COOKIE = "octryx_phone_access"
PHONE_ACCESS_COOKIE_PATH = "/"

SECURE_REASON_FORCED = "forced_by_configuration"
SECURE_REASON_HTTPS = "request_scheme_https"
SECURE_REASON_TRUSTED_PROXY_HTTPS = "trusted_proxy_scheme_https"
SECURE_REASON_FAIL_SECURE = "fail_secure_default"
INSECURE_REASON_LOCAL_DEBUG = "local_debug_loopback_http"


@dataclass(frozen=True)
class AuthCookiePolicy:
    secure: bool
    samesite: str
    secure_reason: str = SECURE_REASON_FAIL_SECURE
    access_token_path: str = ACCESS_TOKEN_COOKIE_PATH
    refresh_token_path: str = REFRESH_TOKEN_COOKIE_PATH

    @property
    def local_debug_exemption(self) -> bool:
        return self.secure_reason == INSECURE_REASON_LOCAL_DEBUG


def _peer_address(request: Request | None, settings: Settings):
    if request is None:
        return None
    return parse_ip_address(client_identity(request, settings).peer_address)


def _is_trusted_proxy_peer(request: Request | None, settings: Settings) -> bool:
    if request is None:
        return False
    return client_identity(request, settings).via_trusted_proxy


def _has_forwarded_headers(request: Request | None) -> bool:
    headers = getattr(request, "headers", None)
    if headers is None:
        return False
    return any(header in headers for header in FORWARDED_REQUEST_HEADERS)


def effective_request_scheme(request: Request | None, settings: Settings) -> str:
    if request is None:
        return ""
    return client_identity(request, settings).scheme


def _local_debug_http_allowed(request: Request | None, settings: Settings) -> bool:
    if not settings.debug or is_production_like_runtime_profile(settings.runtime_profile):
        return False
    address = _peer_address(request, settings)
    if address is None or not address.is_loopback:
        return False
    if _is_trusted_proxy_peer(request, settings) or _has_forwarded_headers(request):
        return False
    return True


def resolve_auth_cookie_policy(
    request: Request | None = None,
    settings: Settings | None = None,
) -> AuthCookiePolicy:
    resolved = settings or get_settings()
    samesite = str(resolved.auth_cookie_samesite or "lax").strip().lower()

    if resolved.force_secure_auth_cookies:
        return AuthCookiePolicy(secure=True, samesite=samesite, secure_reason=SECURE_REASON_FORCED)

    if effective_request_scheme(request, resolved) == "https":
        reason = (
            SECURE_REASON_TRUSTED_PROXY_HTTPS
            if request is not None and client_identity(request, resolved).forwarded_scheme_applied
            else SECURE_REASON_HTTPS
        )
        return AuthCookiePolicy(secure=True, samesite=samesite, secure_reason=reason)

    if _local_debug_http_allowed(request, resolved):
        return AuthCookiePolicy(secure=False, samesite=samesite, secure_reason=INSECURE_REASON_LOCAL_DEBUG)

    return AuthCookiePolicy(secure=True, samesite=samesite, secure_reason=SECURE_REASON_FAIL_SECURE)
