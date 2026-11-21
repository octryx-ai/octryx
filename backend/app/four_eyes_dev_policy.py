"""Where the four-eyes development exception may exist at all.

The platform approval rule (Settings → Governance → "Approval rule")
decides whether an admin may approve their own change. This development exception is
kept beside it: a single developer on a machine-local stack (the local dev backend or
the acceptance stack on localhost:8090) may approve their own governance
request when ``OCTRYX_FOUR_EYES_DEV_SELF_APPROVAL`` is explicitly true.

This module answers the environment half of that question from settings alone, so
``config.Settings`` can refuse startup with it and the runtime gate
(``services.governance.four_eyes``) can re-check it on every decision. It must fail
closed: neither ``DEBUG`` nor the runtime profile alone proves that a deployment is
not production (the acceptance stack runs the production-like ``staging`` profile with
``DEBUG=false``, and a cloud deployment that sets no profile resolves to the default
``local``). The positive evidence required is therefore both of:

* the runtime profile is one of the explicitly named non-production profiles, and
* every configured browser origin (``CORS_ALLOWED_ORIGINS``) is a loopback origin,
  i.e. the stack serves its UI to this machine only. Any network-reachable
  deployment has to name its public origin there, which excludes it.

Only fixed values are inspected; nothing here is logged or echoed.
"""

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
    """True when at least one origin is configured and every one is loopback."""
    origins = [item.strip() for item in str(cors_allowed_origins or "").split(",") if item.strip()]
    return bool(origins) and all(_is_loopback_origin(origin) for origin in origins)


def dev_self_approval_environment_permitted(runtime_profile: str | None, cors_allowed_origins: str | None) -> bool:
    """True only when production is positively excluded for this runtime."""
    profile = str(runtime_profile or "").strip().lower().replace("_", "-")
    return profile in DEV_SELF_APPROVAL_PROFILES and only_loopback_origins(cors_allowed_origins)
