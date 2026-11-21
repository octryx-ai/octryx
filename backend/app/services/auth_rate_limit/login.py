"""The password login's brute-force limits: per client address and per username.

A login attempt is refused while either the address's or the username's failure window is full; a failure
counts against both, and a successful login clears both.
"""

from __future__ import annotations

from fastapi import Request

from .service import (
    AUTH_LOGIN_SCOPE,
    AuthRateLimitState,
    clear_auth_failures,
    clear_username_login_failures,
    get_auth_rate_limit_state,
    get_username_login_state,
    register_auth_failure,
    register_username_login_failure,
)


def state(request: Request, username: str) -> AuthRateLimitState:
    """The address's window when it is full, else the username's (whichever refuses first)."""
    by_address = get_auth_rate_limit_state(AUTH_LOGIN_SCOPE, request)
    return by_address if by_address.limited else get_username_login_state(username)


def register_failure(request: Request, username: str) -> None:
    register_auth_failure(AUTH_LOGIN_SCOPE, request)
    register_username_login_failure(username)


def clear(request: Request, username: str) -> None:
    clear_auth_failures(AUTH_LOGIN_SCOPE, request)
    clear_username_login_failures(username)


__all__ = ["clear", "register_failure", "state"]
