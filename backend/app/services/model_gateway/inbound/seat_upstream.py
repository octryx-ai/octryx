"""HTTP boundary from the seat route to Anthropic.

A ``seat`` session's model traffic goes to ``https://api.anthropic.com`` (``ANTHROPIC_SEAT_UPSTREAM``)
with the user's **own** subscription ``Authorization``, unchanged. Only an allowlist of request
headers travels (:data:`SEAT_FORWARDED_HEADERS`); in particular no ``x-octryx-*`` header
(the session key, Workspace, work item and the seat credential stay on the platform) and no
``x-api-key``. The ``x-stainless-*`` SDK telemetry headers are not forwarded: the Messages API does not
need them (root's live check confirms).

The client is built with ``trust_env=False`` (no proxy or netrc from the platform's environment), no
default credential of its own, no redirects, and the same stream read timeout as the governed route.
The ``Authorization`` value is passed per request and never logged, stored or put into a message.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from .upstream import STREAM_READ_TIMEOUT_SECONDS

SEAT_UPSTREAM_ENV = "ANTHROPIC_SEAT_UPSTREAM"
DEFAULT_SEAT_UPSTREAM = "https://api.anthropic.com"
SEAT_FORWARDED_HEADERS = (
    "authorization",
    "anthropic-version",
    "anthropic-beta",
    "content-type",
    "accept",
    "user-agent",
    "x-app",
    "x-claude-code-session-id",
)
# Response headers handed back to the client unchanged, besides the ``anthropic-ratelimit-*`` family.
_RELAYED_RESPONSE_HEADERS = frozenset({"retry-after", "x-should-retry", "request-id", "content-type"})
_RELAYED_RESPONSE_PREFIX = "anthropic-ratelimit-"
MAX_HEADER_VALUE_CHARS = 8192


REASON_SEAT_UPSTREAM_MISCONFIGURED = "seat_upstream_misconfigured"


def _configured(environ: Mapping[str, str] | None) -> str:
    return str((os.environ if environ is None else environ).get(SEAT_UPSTREAM_ENV) or "").strip().rstrip("/")


def _usable(raw: str) -> bool:
    """``https``, or ``http`` to a loopback host (tests and local stubs only); no userinfo, query or fragment."""
    parts = urlsplit(raw)
    if not parts.netloc or "@" in parts.netloc or parts.query or parts.fragment:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and _is_loopback(parts.hostname or "")


def _is_loopback(host: str) -> bool:
    """A loopback IP literal (``127.0.0.0/8``, ``::1``), or exactly ``localhost``; ``127.0.0.1.evil.com`` is not."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def seat_upstream_base_url(environ: Mapping[str, str] | None = None) -> str:
    """The configured upstream origin; an unusable value never becomes the upstream (it reads as the default)."""
    raw = _configured(environ)
    return raw if raw and _usable(raw) else DEFAULT_SEAT_UPSTREAM


def seat_upstream_problem(environ: Mapping[str, str] | None = None) -> str:
    """``seat_upstream_misconfigured`` when ``ANTHROPIC_SEAT_UPSTREAM`` is set but unusable; else ``""``.

    The seat route refuses every call then: a mistyped or plain-``http`` upstream never silently
    turns into the default, and the subscription token never travels over plain ``http`` off the host.
    """
    raw = _configured(environ)
    return REASON_SEAT_UPSTREAM_MISCONFIGURED if raw and not _usable(raw) else ""


def seat_transport() -> httpx.AsyncBaseTransport | None:
    """Transport seam: ``None`` in production (httpx's own), a mock in tests."""
    return None


def _new_seat_client(base_url: str, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(connect=10.0, read=STREAM_READ_TIMEOUT_SECONDS, write=30.0, pool=10.0),
        transport=transport,
        trust_env=False,
        follow_redirects=False,
    )


# One client per upstream origin and event loop, so a seat call does not pay a TLS handshake of its own. The
# subscription credential travels in the per-call headers, never in the client, so one pooled client serves every caller
# of an upstream. A pool belongs to the loop that opened it: another (or a closed) loop gets its own client.
_SHARED: dict[str, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}


def build_seat_client() -> httpx.AsyncClient:
    """The upstream client for one seat call. Hand it back with :func:`release_seat_client`, never ``aclose``."""
    base_url = seat_upstream_base_url()
    transport = seat_transport()
    if transport is not None:  # a test's mock transport: a client of its own
        return _new_seat_client(base_url, transport)
    loop = asyncio.get_running_loop()
    cached = _SHARED.get(base_url)
    if cached is not None and cached[0] is loop and not cached[1].is_closed:
        return cached[1]
    client = _new_seat_client(base_url, None)
    _SHARED[base_url] = (loop, client)
    return client


async def release_seat_client(client: httpx.AsyncClient) -> None:
    """Ends one call's use of ``client``: a shared client stays open for the next call, an own one is closed."""
    if any(shared is client for _loop, shared in _SHARED.values()):
        return
    await client.aclose()


async def close_seat_clients() -> None:
    """Closes the shared clients (application shutdown)."""
    for _loop, client in list(_SHARED.values()):
        with contextlib.suppress(Exception):
            await client.aclose()
    _SHARED.clear()


def seat_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Exactly the allowlisted request headers, by lower-case name."""
    lowered = {str(name).lower(): str(value) for name, value in headers.items()}
    return {
        name: lowered[name]
        for name in SEAT_FORWARDED_HEADERS
        if lowered.get(name) and len(lowered[name]) <= MAX_HEADER_VALUE_CHARS
    }


def seat_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name in _RELAYED_RESPONSE_HEADERS or name.startswith(_RELAYED_RESPONSE_PREFIX)
    }


__all__ = [
    "DEFAULT_SEAT_UPSTREAM",
    "REASON_SEAT_UPSTREAM_MISCONFIGURED",
    "SEAT_FORWARDED_HEADERS",
    "SEAT_UPSTREAM_ENV",
    "build_seat_client",
    "seat_request_headers",
    "seat_response_headers",
    "seat_transport",
    "seat_upstream_base_url",
    "seat_upstream_problem",
]
