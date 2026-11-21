"""Per-client brute-force limiter for the authentication endpoints.

The login routes also limit failed logins per username (``rate_limit_login_failures_per_username``
per window, default 10/min), so a password guess spread across many addresses meets a limit too. The key is a
hash of the normalized username, never the name itself.

The bucket identity comes from the validated trusted-proxy boundary. The
set of live keys is bounded by ``rate_limit_state_policy`` under exactly
the same policy and the same configured bound as the API limiter: a failure
window that can no longer count anything is evicted, and a hard bound caps the
retained key count however many distinct addresses arrive.
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from fastapi import Request

from ...config import get_settings
from ...rate_limit_state_policy import STORE_AUTH, BoundedKeyStateStore
from ...trusted_proxy_policy import rate_limit_client_key

AUTH_LOGIN_SCOPE = "auth.login"
AUTH_LOGIN_USERNAME_SCOPE = "auth.login_username"
AUTH_REFRESH_SCOPE = "auth.refresh"
AUTH_RATE_LIMIT_MAX_ATTEMPTS = 5
AUTH_RATE_LIMIT_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class AuthRateLimitState:
    limited: bool
    retry_after_seconds: int
    remaining_attempts: int
    attempts_used: int = 0
    max_attempts: int = AUTH_RATE_LIMIT_MAX_ATTEMPTS
    window_seconds: int = AUTH_RATE_LIMIT_WINDOW_SECONDS

    @property
    def retry_after_header_value(self) -> str:
        return str(self.retry_after_seconds)


def _configured_key_capacity() -> int:
    """The configured per-store key bound, read from current settings."""
    return get_settings().max_rate_limit_keys


_ATTEMPTS: BoundedKeyStateStore[deque[float]] = BoundedKeyStateStore(
    STORE_AUTH,
    retention_seconds=AUTH_RATE_LIMIT_WINDOW_SECONDS,
    capacity_provider=_configured_key_capacity,
    new_state=deque,
)
# Every mutation of the store happens inside this lock: the auth limiter is called
# from synchronous request handling, so mutual exclusion has to hold across
# threads, not only across coroutines.
_LOCK = Lock()


def _client_ip(request: Request) -> str:
    """Effective client address, resolved at the trusted-proxy boundary.

    A forwarded header from an untrusted peer cannot move the brute-force bucket.
    """
    return rate_limit_client_key(request)


def _bucket_key(scope: str, request: Request) -> str:
    return f"{scope}:{_client_ip(request)}"


def _prune(bucket: deque[float], now: float, window_seconds: int) -> None:
    cutoff = now - window_seconds
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()


def _build_auth_rate_limit_state(
    bucket: deque[float], *, now: float, max_attempts: int = AUTH_RATE_LIMIT_MAX_ATTEMPTS
) -> AuthRateLimitState:
    count = len(bucket)
    if count >= max_attempts:
        retry_after = max(1, int(AUTH_RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
        return AuthRateLimitState(
            limited=True,
            retry_after_seconds=retry_after,
            remaining_attempts=0,
            attempts_used=count,
            max_attempts=max_attempts,
        )
    return AuthRateLimitState(
        limited=False,
        retry_after_seconds=0,
        remaining_attempts=max(0, max_attempts - count),
        attempts_used=count,
        max_attempts=max_attempts,
    )


def _evaluate_auth_rate_limit(scope: str, request: Request, *, read_only: bool) -> AuthRateLimitState:
    """Evaluate, and for a failure record, one client's auth attempt window.

    A read-only evaluation never creates a key: an absent key is an empty window,
    which is the same answer, and answering a read must not grow bounded state.
    """
    now = monotonic()
    key = _bucket_key(scope, request)
    with _LOCK:
        bucket = _ATTEMPTS.peek(key) if read_only else _ATTEMPTS.touch(key, now=now)
        if bucket is None:
            return _build_auth_rate_limit_state(deque(), now=now)
        _prune(bucket, now, AUTH_RATE_LIMIT_WINDOW_SECONDS)
        if not read_only:
            bucket.append(now)
        return _build_auth_rate_limit_state(bucket, now=now)


def get_auth_rate_limit_state(scope: str, request: Request) -> AuthRateLimitState:
    return _evaluate_auth_rate_limit(scope, request, read_only=True)


def register_auth_failure(scope: str, request: Request) -> AuthRateLimitState:
    return _evaluate_auth_rate_limit(scope, request, read_only=False)


def clear_auth_failures(scope: str, request: Request) -> None:
    key = _bucket_key(scope, request)
    with _LOCK:
        # The product decided this window is finished (a successful login), which
        # is not a retention event and is not counted as an eviction.
        _ATTEMPTS.discard(key)


def _username_key(username: str) -> str:
    digest = hashlib.sha256(str(username or "").strip().lower().encode()).hexdigest()[:32]
    return f"{AUTH_LOGIN_USERNAME_SCOPE}:{digest}"


def _evaluate_username(username: str, *, read_only: bool) -> AuthRateLimitState:
    now = monotonic()
    key = _username_key(username)
    max_attempts = int(get_settings().rate_limit_login_failures_per_username)
    with _LOCK:
        bucket = _ATTEMPTS.peek(key) if read_only else _ATTEMPTS.touch(key, now=now)
        if bucket is None:
            return _build_auth_rate_limit_state(deque(), now=now, max_attempts=max_attempts)
        _prune(bucket, now, AUTH_RATE_LIMIT_WINDOW_SECONDS)
        if not read_only:
            bucket.append(now)
        return _build_auth_rate_limit_state(bucket, now=now, max_attempts=max_attempts)


def get_username_login_state(username: str) -> AuthRateLimitState:
    """Whether failed logins for ``username`` (from any address) reached the per-username limit."""
    return _evaluate_username(username, read_only=True)


def register_username_login_failure(username: str) -> AuthRateLimitState:
    return _evaluate_username(username, read_only=False)


def clear_username_login_failures(username: str) -> None:
    with _LOCK:
        _ATTEMPTS.discard(_username_key(username))


def clear_all_auth_rate_limits() -> None:
    with _LOCK:
        _ATTEMPTS.clear()
