"""HTTP boundary from the Codex seat route to ChatGPT's Codex backend."""

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
    return _usable(raw) and urlsplit(raw).path == CODEX_SEAT_BASE_PATH


def codex_seat_upstream_origin(environ: Mapping[str, str] | None = None) -> str:
    raw = _configured(environ)
    parts = urlsplit(raw if raw and _allowed(raw) else DEFAULT_CODEX_SEAT_UPSTREAM)
    return f"{parts.scheme}://{parts.netloc}"


# An override must be https (http only to a loopback host) and keep exactly the base path; anything else refuses every
# call instead of becoming the default.
def codex_seat_upstream_problem(environ: Mapping[str, str] | None = None) -> str:
    raw = _configured(environ)
    return REASON_CODEX_SEAT_UPSTREAM_MISCONFIGURED if raw and not _allowed(raw) else ""


def codex_seat_transport() -> httpx.AsyncBaseTransport | None:
    return None


def build_codex_seat_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=codex_seat_upstream_origin(),
        timeout=httpx.Timeout(connect=10.0, read=STREAM_READ_TIMEOUT_SECONDS, write=30.0, pool=10.0),
        transport=codex_seat_transport(),
        trust_env=False,
        follow_redirects=False,
    )


# Only what codex-rs sends on a Responses call travels: no x-octryx-*, no cookie, no x-codex-turn-metadata (Workspace
# and git details).
def codex_seat_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
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
