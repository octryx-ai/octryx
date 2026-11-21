from __future__ import annotations

from starlette.requests import Request

import app.services.auth_rate_limit as auth_rate_limit
import app.services.auth_rate_limit as auth_rate_limit_service
from app.services.auth_rate_limit import (
    AUTH_LOGIN_SCOPE,
    AuthRateLimitState,
    clear_all_auth_rate_limits,
    clear_auth_failures,
    get_auth_rate_limit_state,
    register_auth_failure,
)
from app.services.auth_rate_limit import service as auth_rate_limit_package


def _make_request(*, client_host: str = "127.0.0.1", forwarded_for: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("latin-1")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": headers,
        "client": (client_host, 12345),
        "query_string": b"",
    }
    return Request(scope)


def test_auth_rate_limit_service_root_shim_matches_package_surface() -> None:
    assert auth_rate_limit_service.AUTH_LOGIN_SCOPE == auth_rate_limit.AUTH_LOGIN_SCOPE
    assert auth_rate_limit_service.AUTH_RATE_LIMIT_MAX_ATTEMPTS == auth_rate_limit.AUTH_RATE_LIMIT_MAX_ATTEMPTS
    assert auth_rate_limit_service.AUTH_RATE_LIMIT_WINDOW_SECONDS == auth_rate_limit.AUTH_RATE_LIMIT_WINDOW_SECONDS
    assert auth_rate_limit_service.AuthRateLimitState is auth_rate_limit.AuthRateLimitState
    assert auth_rate_limit_service.clear_all_auth_rate_limits is auth_rate_limit.clear_all_auth_rate_limits
    assert auth_rate_limit_service.clear_auth_failures is auth_rate_limit.clear_auth_failures
    assert auth_rate_limit_service.get_auth_rate_limit_state is auth_rate_limit.get_auth_rate_limit_state
    assert auth_rate_limit_service.register_auth_failure is auth_rate_limit.register_auth_failure


def test_auth_rate_limit_state_reports_attempt_metadata(monkeypatch):
    clear_all_auth_rate_limits()
    request = _make_request()
    current_time = [100.0]
    monkeypatch.setattr(auth_rate_limit_package, "monotonic", lambda: current_time[0])

    state = get_auth_rate_limit_state(AUTH_LOGIN_SCOPE, request)

    assert isinstance(state, AuthRateLimitState)
    assert state.limited is False
    assert state.retry_after_seconds == 0
    assert state.retry_after_header_value == "0"
    assert state.remaining_attempts == 5
    assert state.attempts_used == 0
    assert state.max_attempts == 5
    assert state.window_seconds == 60


def test_auth_rate_limit_records_failures_and_exposes_retry_after(monkeypatch):
    clear_all_auth_rate_limits()
    request = _make_request(forwarded_for="10.0.0.1, 10.0.0.2")
    current_time = [100.0]
    monkeypatch.setattr(auth_rate_limit_package, "monotonic", lambda: current_time[0])

    state = None
    for _ in range(5):
        state = register_auth_failure(AUTH_LOGIN_SCOPE, request)

    assert state is not None
    assert state.limited is True
    assert state.retry_after_seconds == 60
    assert state.retry_after_header_value == "60"
    assert state.remaining_attempts == 0
    assert state.attempts_used == 5

    limited_state = get_auth_rate_limit_state(AUTH_LOGIN_SCOPE, request)
    assert limited_state.limited is True
    assert limited_state.retry_after_seconds == 60
    assert limited_state.remaining_attempts == 0
    assert limited_state.attempts_used == 5


def test_auth_rate_limit_window_expires_and_clear_removes_bucket(monkeypatch):
    clear_all_auth_rate_limits()
    request = _make_request(client_host="192.0.2.15")
    current_time = [100.0]
    monkeypatch.setattr(auth_rate_limit_package, "monotonic", lambda: current_time[0])

    for _ in range(5):
        register_auth_failure(AUTH_LOGIN_SCOPE, request)

    current_time[0] = 159.0
    limited_state = get_auth_rate_limit_state(AUTH_LOGIN_SCOPE, request)
    assert limited_state.limited is True
    assert limited_state.retry_after_seconds == 1

    clear_auth_failures(AUTH_LOGIN_SCOPE, request)
    cleared_state = get_auth_rate_limit_state(AUTH_LOGIN_SCOPE, request)
    assert cleared_state.limited is False
    assert cleared_state.remaining_attempts == 5
    assert cleared_state.attempts_used == 0

    current_time[0] = 161.0
    expired_state = get_auth_rate_limit_state(AUTH_LOGIN_SCOPE, request)
    assert expired_state.limited is False
    assert expired_state.remaining_attempts == 5
    assert expired_state.attempts_used == 0

    clear_all_auth_rate_limits()
