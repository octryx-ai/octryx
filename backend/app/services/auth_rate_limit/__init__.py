"""Canonical package surface for auth rate limit services."""

from .service import (
    AUTH_LOGIN_SCOPE,
    AUTH_RATE_LIMIT_MAX_ATTEMPTS,
    AUTH_RATE_LIMIT_WINDOW_SECONDS,
    AUTH_REFRESH_SCOPE,
    AuthRateLimitState,
    clear_all_auth_rate_limits,
    clear_auth_failures,
    clear_username_login_failures,
    get_auth_rate_limit_state,
    get_username_login_state,
    register_auth_failure,
    register_username_login_failure,
)

__all__ = [
    "AUTH_LOGIN_SCOPE",
    "AUTH_REFRESH_SCOPE",
    "AUTH_RATE_LIMIT_MAX_ATTEMPTS",
    "AUTH_RATE_LIMIT_WINDOW_SECONDS",
    "AuthRateLimitState",
    "clear_all_auth_rate_limits",
    "clear_auth_failures",
    "clear_username_login_failures",
    "get_auth_rate_limit_state",
    "get_username_login_state",
    "register_auth_failure",
    "register_username_login_failure",
]
