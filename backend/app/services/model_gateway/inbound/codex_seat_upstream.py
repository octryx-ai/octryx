"""HTTP boundary from the Codex seat route to ChatGPT's Codex backend (``codex_seat``).

A Codex seat session's model traffic goes to ``https://chatgpt.com/backend-api/codex``
(``OCTRYX_CODEX_SEAT_UPSTREAM``) with the person's **own** ChatGPT ``Authorization``, unchanged. Only one
upstream path is ever reached: :data:`CODEX_SEAT_RESPONSES_PATH` (``/backend-api/codex/responses``). An override
must be ``https`` (or ``http`` to a loopback host, for tests and local stubs) and keep exactly that base path; any
other value refuses every call (``codex_seat_upstream_misconfigured``) instead of becoming the default.

Only an allowlist of request headers travels (:data:`CODEX_SEAT_FORWARDED_HEADERS`, what codex-rs sends on a
Responses call: its ChatGPT login, account, beta flag, originator, version and correlation ids); in particular no
``x-octryx-*`` header, no cookie and not ``x-codex-turn-metadata`` (workspace and git details). Response
headers: a small allowlist plus the ``x-codex-*`` family (rate-limit windows, credits, sticky ``x-codex-turn-state``).

The client is built with ``trust_env=False``, no credential of its own and no redirects. The ``Authorization``
value is passed per request and never logged, stored or put into a message.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from .seat_upstream import MAX_HEADER_VALUE_CHARS, _usable
from .upstream import STREAM_READ_TIMEOUT_SECONDS

CODEX_SEAT_UPSTREAM_ENV = "OCTRYX_CODEX_SEAT_UPSTREAM"
CODEX_SEAT_BASE_PATH = "/backend-api/codex"
DEFAULT_CODEX_SEAT_UPSTREAM = "https://chatgpt.com" + CODEX_SEAT_BASE_PATH
# The only upstream path this route reaches (allowlist of one).
CODEX_SEAT_RESPONSES_PATH = CODEX_SEAT_BASE_PATH + "/responses"
CODEX_SEAT_FORWARDED_HEADERS = (
    "authorization",
    "chatgpt-account-id",
    "openai-beta",
    "originator",
    "session_id",
    "session-id",
    "thread-id",
    "version",
    "user-agent",
    "accept",
    "content-type",
    "x-openai-subagent",
    "x-codex-turn-state",
)
_RELAYED_RESPONSE_HEADERS = frozenset({
    "content-type", "retry-after", "x-request-id", "x-oai-request-id", "openai-model", "x-openai-model",
    "x-reasoning-included",
})
_RELAYED_RESPONSE_PREFIX = "x-codex-"
REASON_CODEX_SEAT_UPSTREAM_MISCONFIGURED = "codex_seat_upstream_misconfigured"


def _configured(environ: Mapping[str, str] | None) -> str:
    return str((os.environ if environ is None else environ).get(CODEX_SEAT_UPSTREAM_ENV) or "").strip().rstrip("/")


def _allowed(raw: str) -> bool:
    """Usable as the seat upstream (``seat_upstream._usable``) and exactly the Codex backend's base path."""
    return _usable(raw) and urlsplit(raw).path == CODEX_SEAT_BASE_PATH


def codex_seat_upstream_origin(environ: Mapping[str, str] | None = None) -> str:
    """``scheme://host[:port]`` of the configured upstream (the default when unset or unusable)."""
    raw = _configured(environ)
    parts = urlsplit(raw if raw and _allowed(raw) else DEFAULT_CODEX_SEAT_UPSTREAM)
    return f"{parts.scheme}://{parts.netloc}"


def codex_seat_upstream_problem(environ: Mapping[str, str] | None = None) -> str:
    """``codex_seat_upstream_misconfigured`` when the override is set but not allowed; else ``""``."""
    raw = _configured(environ)
    return REASON_CODEX_SEAT_UPSTREAM_MISCONFIGURED if raw and not _allowed(raw) else ""


def codex_seat_transport() -> httpx.AsyncBaseTransport | None:
    """Transport seam: ``None`` in production (httpx's own), a mock in tests."""
    return None


def build_codex_seat_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=codex_seat_upstream_origin(),
        timeout=httpx.Timeout(connect=10.0, read=STREAM_READ_TIMEOUT_SECONDS, write=30.0, pool=10.0),
        transport=codex_seat_transport(),
        trust_env=False,
        follow_redirects=False,
    )


def codex_seat_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Exactly the allowlisted request headers, by lower-case name."""
    lowered = {str(name).lower(): str(value) for name, value in headers.items()}
    return {
        name: lowered[name]
        for name in CODEX_SEAT_FORWARDED_HEADERS
        if lowered.get(name) and len(lowered[name]) <= MAX_HEADER_VALUE_CHARS
    }


def codex_seat_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name in _RELAYED_RESPONSE_HEADERS or name.startswith(_RELAYED_RESPONSE_PREFIX)
    }


__all__ = [
    "CODEX_SEAT_FORWARDED_HEADERS",
    "CODEX_SEAT_RESPONSES_PATH",
    "CODEX_SEAT_UPSTREAM_ENV",
    "DEFAULT_CODEX_SEAT_UPSTREAM",
    "REASON_CODEX_SEAT_UPSTREAM_MISCONFIGURED",
    "build_codex_seat_client",
    "codex_seat_request_headers",
    "codex_seat_response_headers",
    "codex_seat_transport",
    "codex_seat_upstream_origin",
    "codex_seat_upstream_problem",
]
