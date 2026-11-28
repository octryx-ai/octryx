"""Where the four-eyes development exception may exist at all."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

DEV_SELF_APPROVAL_PROFILES = frozenset({"local", "dev", "development", "test", "testing", "staging"})
_LOOPBACK_HOSTNAMES = frozenset({"localhost"})
_ORIGIN_SCHEMES = frozenset({"http", "https"})


def _is_loopback_origin(origin: str) -> bool:
    try:
        parts = urlsplit(origin)
        hostname = parts.hostname
    except ValueError:
        return False
    if parts.scheme not in _ORIGIN_SCHEMES or not hostname:
        return False
    if hostname in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def only_loopback_origins(cors_allowed_origins: str | None) -> bool:
    origins = [item.strip() for item in str(cors_allowed_origins or "").split(",") if item.strip()]
    return bool(origins) and all(_is_loopback_origin(origin) for origin in origins)


def dev_self_approval_environment_permitted(runtime_profile: str | None, cors_allowed_origins: str | None) -> bool:
    profile = str(runtime_profile or "").strip().lower().replace("_", "-")
    return profile in DEV_SELF_APPROVAL_PROFILES and only_loopback_origins(cors_allowed_origins)
