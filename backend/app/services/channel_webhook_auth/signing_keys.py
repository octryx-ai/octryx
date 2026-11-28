"""Published signing keys of a Microsoft token issuer, cached."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

KEY_CACHE_SECONDS = 24 * 3600
MIN_REFRESH_SECONDS = 300
RETRY_AFTER_FAILURE_SECONDS = 30
_FETCH_TIMEOUT_SECONDS = 10.0


class SigningKeysUnavailableError(Exception):
    pass


class SigningKeySource(Protocol):
    async def keys(self, *, refresh: bool = False) -> list[dict[str, Any]]: ...


JsonFetcher = Callable[[str], Awaitable[Any]]


async def _fetch_json(url: str) -> Any:
    from ..outbound_egress.public_web import public_web_client

    async with public_web_client(
        timeout=_FETCH_TIMEOUT_SECONDS, globally_routable_only=True, follow_redirects=False
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


class OpenIdSigningKeySource:
    def __init__(
        self,
        openid_url: str,
        *,
        jwks_hosts: frozenset[str],
        fetch_json: JsonFetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._openid_url = openid_url
        self._jwks_hosts = jwks_hosts
        self._fetch_json = fetch_json or _fetch_json
        self._clock = clock
        self._keys: list[dict[str, Any]] | None = None
        self._fetched_at = 0.0
        self._failed_at: float | None = None
        self._lock = asyncio.Lock()

    async def keys(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        async with self._lock:
            now = self._clock()
            stale = self._keys is None or now - self._fetched_at > KEY_CACHE_SECONDS
            may_refresh = refresh and now - self._fetched_at >= MIN_REFRESH_SECONDS
            if stale or may_refresh:
                if self._failed_at is not None and now - self._failed_at < RETRY_AFTER_FAILURE_SECONDS:
                    if stale:
                        raise SigningKeysUnavailableError("signing_keys_fetch_failed")
                    return list(self._keys or [])
                try:
                    self._keys = await self._load()
                except SigningKeysUnavailableError:
                    self._failed_at = now
                    raise
                self._fetched_at = now
                self._failed_at = None
            return list(self._keys or [])

    async def _load(self) -> list[dict[str, Any]]:
        try:
            metadata = await self._fetch_json(self._openid_url)
            jwks_uri = str(metadata.get("jwks_uri") or "") if isinstance(metadata, dict) else ""
            parts = urlsplit(jwks_uri)
            if parts.scheme != "https" or (parts.hostname or "") not in self._jwks_hosts:
                raise SigningKeysUnavailableError("jwks_uri_not_allowed")
            key_set = await self._fetch_json(jwks_uri)
        except SigningKeysUnavailableError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise SigningKeysUnavailableError("signing_keys_fetch_failed") from None
        keys = key_set.get("keys") if isinstance(key_set, dict) else None
        if not isinstance(keys, list) or not all(isinstance(key, dict) for key in keys):
            raise SigningKeysUnavailableError("signing_keys_malformed")
        return keys


class StaticSigningKeySource:
    def __init__(self, keys: list[dict[str, Any]]) -> None:
        self._keys = list(keys)

    async def keys(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        return list(self._keys)


__all__ = [
    "KEY_CACHE_SECONDS",
    "MIN_REFRESH_SECONDS",
    "OpenIdSigningKeySource",
    "SigningKeySource",
    "SigningKeysUnavailableError",
    "StaticSigningKeySource",
]
