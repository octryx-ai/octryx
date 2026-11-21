"""Rate-limit settings (key bound, per-user limits), a base of :class:`app.config.Settings`.

Every limit is per minute and can be overridden from the environment:

- ``OCTRYX_RATE_LIMIT_USER_READ_PER_MIN`` (default 3000): ``GET``/``HEAD``/``OPTIONS`` of one
  authenticated user, a runaway-loop guard that a person clicking around never reaches;
- ``OCTRYX_RATE_LIMIT_USER_WRITE_PER_MIN`` (default 600): writes of one authenticated user;
- ``OCTRYX_RATE_LIMIT_IP_GENERAL_PER_MIN`` (default 120) and ``..._IP_WRITE_PER_MIN`` (default 30):
  unauthenticated requests per client address;
- ``OCTRYX_RATE_LIMIT_AUTH_PER_MIN`` (default 20): ``/api/v1/auth/*`` per client address;
- ``OCTRYX_RATE_LIMIT_LOGIN_FAILURES_PER_USERNAME`` (default 10): failed logins per username.

``OCTRYX_DISABLE_API_RATE_LIMIT=1`` still disables the API limiter (tests, local tooling).
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from .rate_limit_state_policy import DEFAULT_MAX_RATE_LIMIT_KEYS


def _limit(name: str, default: int):
    return Field(default=default, ge=1, validation_alias=AliasChoices(name, f"OCTRYX_{name.upper()}"))


class RateLimitSettings(BaseSettings):
    # Hard bound on the number of client keys each in-memory rate limiter
    # retains. It applies per limiter store (API addresses, API users and auth), so one
    # process retains at most three times this many keys, and a deployment with several
    # replicas multiplies that by the replica count. Invalid values fail startup — see
    # rate_limit_state_policy.
    max_rate_limit_keys: int = Field(
        default=DEFAULT_MAX_RATE_LIMIT_KEYS,
        validation_alias=AliasChoices("max_rate_limit_keys", "OCTRYX_MAX_RATE_LIMIT_KEYS"),
    )
    rate_limit_user_read_per_min: int = _limit("rate_limit_user_read_per_min", 3000)
    rate_limit_user_write_per_min: int = _limit("rate_limit_user_write_per_min", 600)
    rate_limit_ip_general_per_min: int = _limit("rate_limit_ip_general_per_min", 120)
    rate_limit_ip_write_per_min: int = _limit("rate_limit_ip_write_per_min", 30)
    rate_limit_auth_per_min: int = _limit("rate_limit_auth_per_min", 20)
    rate_limit_login_failures_per_username: int = _limit("rate_limit_login_failures_per_username", 10)


__all__ = ["RateLimitSettings"]
