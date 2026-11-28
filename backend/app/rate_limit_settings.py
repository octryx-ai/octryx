"""Rate-limit settings (key bound, per-user limits), a base of :class:`app.config.Settings`."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from .rate_limit_state_policy import DEFAULT_MAX_RATE_LIMIT_KEYS


def _limit(name: str, default: int):
    return Field(default=default, ge=1, validation_alias=AliasChoices(name, f"OCTRYX_{name.upper()}"))


class RateLimitSettings(BaseSettings):
    # Bound per limiter store (three per process, times replicas); invalid values fail startup.
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
