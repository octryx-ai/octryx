"""Provider health for the governed web search: quarantine on anomalies, and a canary probe.

A provider that answers a domain-restricted query with a result outside the restriction is not
behaving like a search API any more (a bot page, a hijacked answer, a changed contract). Its answer
is discarded as a whole and the provider is quarantined for :data:`QUARANTINE_SECONDS`; search is
``unavailable`` until then, or until a canary probe passes.

The canary is a fixed query restricted to one known documentation host. It passes when the provider
returns at least one result and every result is on that host and clear of the blocklist.

The quarantine is process-local: each API process learns it on its own first anomaly.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from .blocklist import platform_blocklist
from .providers import ProviderConfig, SearchProviderError, search_provider

logger = logging.getLogger(__name__)

QUARANTINE_SECONDS = 900
CANARY_QUERY = "Python standard library documentation"
CANARY_HOST = "docs.python.org"
_quarantine: dict[str, tuple[float, str]] = {}


def quarantine_reason(provider: str) -> str | None:
    entry = _quarantine.get(provider)
    if entry is None:
        return None
    until, reason = entry
    if time.monotonic() >= until:
        _quarantine.pop(provider, None)
        return None
    return reason


def quarantine(provider: str, reason: str) -> None:
    _quarantine[provider] = (time.monotonic() + QUARANTINE_SECONDS, reason)
    logger.warning("Web search provider quarantined: provider=%s reason=%s", provider, reason)


def release(provider: str) -> None:
    _quarantine.pop(provider, None)


def host_within(host: str, domains: list[str]) -> bool:
    host = host.lower().removeprefix("www.")
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


async def canary(config: ProviderConfig, *, client_factory: Callable[..., Any] = httpx.AsyncClient) -> dict[str, Any]:
    """Probe the provider with the fixed canary query; quarantines or releases it."""
    try:
        hits = await search_provider(
            config,
            query=CANARY_QUERY,
            num_results=5,
            include_domains=[CANARY_HOST],
            exclude_domains=[],
            client_factory=client_factory,
        )
    except SearchProviderError as error:
        return {"provider": config.name, "healthy": False, "reason": error.reason}
    off_host = [hit for hit in hits if not host_within(urlsplit(hit.url).hostname or "", [CANARY_HOST])]
    blocked = [hit for hit in hits if platform_blocklist().category_of(hit.url)]
    if not hits:
        return {"provider": config.name, "healthy": False, "reason": "no_results"}
    if off_host or blocked:
        quarantine(config.name, "canary_off_restriction")
        return {"provider": config.name, "healthy": False, "reason": "canary_off_restriction"}
    release(config.name)
    return {"provider": config.name, "healthy": True, "reason": "ok", "results": len(hits)}


__all__ = ["CANARY_HOST", "QUARANTINE_SECONDS", "canary", "host_within", "quarantine", "quarantine_reason", "release"]
