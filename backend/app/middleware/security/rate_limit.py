"""In-memory sliding-window rate limiter for API endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from ...config import Settings, get_settings
from ...rate_limit_state_policy import STORE_API, STORE_API_USER, BoundedKeyStateStore
from ...trusted_proxy_policy import rate_limit_client_key
from .rate_limit_identity import request_principal

logger = logging.getLogger(__name__)

# --- Scope configurations --------------------------------------------------

API_GENERAL_SCOPE = "api.general"
API_WRITE_SCOPE = "api.write"
API_AUTH_SCOPE = "api.auth"
API_HEAVY_SCOPE = "api.heavy"
API_AGENT_GATEWAY_SCOPE = "api.agent_gateway"
API_USER_READ_SCOPE = "api.user_read"
API_USER_WRITE_SCOPE = "api.user_write"


@dataclass(frozen=True)
class RateLimitScope:
    max_requests: int
    window_seconds: int
    key_prefix: str
    # The public name a 429 carries, and the ``Settings`` field that overrides ``max_requests``.
    label: str = ""
    setting: str | None = None


_API_SCOPES: dict[str, RateLimitScope] = {
    API_GENERAL_SCOPE: RateLimitScope(120, 60, "api", "ip_general", "rate_limit_ip_general_per_min"),
    API_WRITE_SCOPE: RateLimitScope(30, 60, "write", "ip_write", "rate_limit_ip_write_per_min"),
    API_AUTH_SCOPE: RateLimitScope(20, 60, "auth", "auth", "rate_limit_auth_per_min"),
    API_HEAVY_SCOPE: RateLimitScope(30, 60, "heavy", "heavy"),
    API_AGENT_GATEWAY_SCOPE: RateLimitScope(600, 60, "agent_gateway", "agent_gateway"),
    API_USER_READ_SCOPE: RateLimitScope(3000, 60, "read", "user_read", "rate_limit_user_read_per_min"),
    API_USER_WRITE_SCOPE: RateLimitScope(600, 60, "user_write", "user_write", "rate_limit_user_write_per_min"),
}

# Paths that are always excluded from rate limiting (health checks, etc.)
_RATE_LIMIT_EXEMPT_PATHS = frozenset({
    "/healthz",
    "/ready",
    "/metrics",
    "/favicon.ico",
})

# Every static mount of ``http_setup.py``. Vite serves every JS/CSS chunk from them, including each lazily
# loaded admin tab; counting these public files against an API budget lets a spent budget block the app's own
# code. Only safe methods are exempt; any other method keeps its scope, since mutating requests
# write audit rows. ``/chat/static`` requests may still record request metrics, but are never limited.
_STATIC_ASSET_MOUNT_PREFIXES = ("/admin/static/", "/chat/static/")
_STATIC_ASSET_MOUNT_PREFIX = _STATIC_ASSET_MOUNT_PREFIXES[0]
_STATIC_ASSET_READ_METHODS = frozenset({"GET", "HEAD"})
# The SPA and server-rendered page shells: ``/chat``, ``/admin`` and their one-level pages (``/admin/chat``,
# ``/admin/settings``, ``/admin/login``, ...), never an ``api`` or ``static`` segment.
_PAGE_SHELL = re.compile(r"^/(?:chat|admin)(?:/(?!(?:api|static)/?$)[a-z][a-z0-9-]*)?/?$")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Paths that use the heavy scope (expensive operations)
_RATE_LIMIT_HEAVY_PATHS = frozenset({
    "/api/v1/tasks/reload",
    "/api/v1/sessions/bulk",
})

# An external coding client (octryx-claude) makes a model call per agent step plus
# parallel utility calls, and a hook call per tool use. These bearer-authenticated
# surfaces get their own, larger budget (per user when the bearer verifies here,
# else per address); per-user policy beyond it is the budget service's job.
_AGENT_GATEWAY_PATH_PREFIXES = ("/api/v1/model-gateway/", "/api/v1/agent-gateway/")

_DISABLE_RATE_LIMIT_ENV = "OCTRYX_DISABLE_API_RATE_LIMIT"


# --- Tracking buckets -------------------------------------------------------

@dataclass
class _RateLimitBucket:
    timestamps: list[float] = field(default_factory=list)

    def count(self, now: float, window: int) -> int:
        cutoff = now - window
        i = 0
        while i < len(self.timestamps) and self.timestamps[i] < cutoff:
            i += 1
        return len(self.timestamps) - i

    def prune_and_append(self, now: float, window: int) -> int:
        cutoff = now - window
        i = 0
        while i < len(self.timestamps) and self.timestamps[i] < cutoff:
            i += 1
        if i > 0:
            del self.timestamps[:i]
        self.timestamps.append(now)
        return len(self.timestamps)


def _configured_key_capacity() -> int:
    return get_settings().max_rate_limit_keys


# Retention is the widest configured scope window, so a bucket is only evicted as
# stale once no scope could still count a timestamp in it. Deriving it from the
# scope table means adding a longer window widens retention instead of silently
# under-retaining that scope.
_KEY_RETENTION_SECONDS = max(scope.window_seconds for scope in _API_SCOPES.values())

_BUCKETS: BoundedKeyStateStore[_RateLimitBucket] = BoundedKeyStateStore(
    STORE_API,
    retention_seconds=_KEY_RETENTION_SECONDS,
    capacity_provider=_configured_key_capacity,
    new_state=_RateLimitBucket,
)
_USER_BUCKETS: BoundedKeyStateStore[_RateLimitBucket] = BoundedKeyStateStore(
    STORE_API_USER,
    retention_seconds=_KEY_RETENTION_SECONDS,
    capacity_provider=_configured_key_capacity,
    new_state=_RateLimitBucket,
)
# Held across the whole read-decide-write section below. The section contains no
# ``await``, so admissions already could not interleave; acquiring the lock makes
# that a property of the code rather than of the current statement order, now that
# the section also mutates shared retention bookkeeping.
_BUCKETS_LOCK = asyncio.Lock()


def _client_ip(request: Request) -> str:
    return rate_limit_client_key(request)


def _determine_scope(path: str, method: str, *, authenticated: bool = False) -> str:
    if path.startswith(_AGENT_GATEWAY_PATH_PREFIXES):
        return API_AGENT_GATEWAY_SCOPE
    if path in _RATE_LIMIT_HEAVY_PATHS:
        return API_HEAVY_SCOPE
    if path.startswith("/api/v1/auth"):
        return API_AUTH_SCOPE
    if authenticated:
        return API_USER_READ_SCOPE if method.upper() in _SAFE_METHODS else API_USER_WRITE_SCOPE
    if method.upper() in _WRITE_METHODS:
        return API_WRITE_SCOPE
    return API_GENERAL_SCOPE


def _is_static_asset_read(request: Request) -> bool:
    return request.method in _STATIC_ASSET_READ_METHODS and request.url.path.startswith(_STATIC_ASSET_MOUNT_PREFIXES)


def _is_page_shell_read(request: Request) -> bool:
    return request.method in _STATIC_ASSET_READ_METHODS and bool(_PAGE_SHELL.match(request.url.path))


def _should_exempt(request: Request) -> bool:
    return (
        os.getenv(_DISABLE_RATE_LIMIT_ENV) == "1"
        or request.url.path in _RATE_LIMIT_EXEMPT_PATHS
        or _is_static_asset_read(request)
        or _is_page_shell_read(request)
    )


def _scope_limit(scope: RateLimitScope) -> int:
    return int(getattr(get_settings(), scope.setting)) if scope.setting else scope.max_requests


async def _check_rate_limit(
    scope_key: str, max_requests: int, window_seconds: int, *, store: BoundedKeyStateStore | None = None
) -> tuple[bool, int, int]:
    now = monotonic()
    async with _BUCKETS_LOCK:
        bucket = (store if store is not None else _BUCKETS).touch(scope_key, now=now)
        count = bucket.count(now, window_seconds)
        if count >= max_requests:
            retry_after = max(1, int(window_seconds - (now - bucket.timestamps[0])))
            return True, 0, retry_after
        bucket.prune_and_append(now, window_seconds)
        return False, max_requests - count - 1, 0


def _rate_limit_identity(request: Request) -> tuple[str, str]:
    path = request.url.path
    principal = None if path.startswith("/api/v1/auth") else request_principal(request)
    scope = _determine_scope(path, request.method, authenticated=principal is not None)
    return scope, f"{principal or _client_ip(request)}:{_API_SCOPES[scope].key_prefix}"


async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    """FastAPI middleware that enforces per-user (authenticated) or per-address limits per scope."""
    if _should_exempt(request):
        return await call_next(request)

    scope, scope_key = _rate_limit_identity(request)
    scope_config = _API_SCOPES[scope]
    limit = _scope_limit(scope_config)
    store = _USER_BUCKETS if scope_key.startswith("user:") else _BUCKETS
    limited, remaining, retry_after = await _check_rate_limit(
        scope_key, limit, scope_config.window_seconds, store=store
    )
    label = scope_config.label or scope_config.key_prefix
    if limited:
        return JSONResponse(
            status_code=429,
            content={
                "detail": f"Rate limit exceeded. Retry after {retry_after} seconds.",
                "code": f"rate_limit_{label}",
                "scope": label,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Window": str(scope_config.window_seconds),
                "X-RateLimit-Scope": label,
            },
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Window"] = str(scope_config.window_seconds)
    response.headers["X-RateLimit-Scope"] = label
    return response


def clear_rate_limit_buckets() -> None:
    _BUCKETS.clear()
    _USER_BUCKETS.clear()


def log_rate_limit_retention_configuration(settings: Settings | None = None) -> int:
    """Log the active per-store key bound once at startup and return it."""
    resolved = settings or get_settings()
    bound = int(resolved.max_rate_limit_keys)
    logger.info(
        "Rate-limit key retention active (max_rate_limit_keys=%s per limiter store, retention_seconds=%s)",
        bound,
        _KEY_RETENTION_SECONDS,
    )
    return bound
