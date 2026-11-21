"""Read-only JSON requests against a source system, with every failure mapped to a fixed reason.

Connectors only ever read: this module offers ``GET`` and exactly one ``POST``, Jira Cloud's read-only
issue search (:data:`JIRA_SEARCH_JQL_PATH`, which takes its query as a JSON body), and nothing else, so a
sync can never write to a Confluence or Jira instance. The POST goes through the same governed path as
every GET (egress, backoff, status reasons, size cap, no redirects).

Redirects are not followed (a redirect off the configured base URL would carry the credential
elsewhere). Every request goes through the pinned egress transport
of its connection kind (``egress.py``), so a URL that resolves to a loopback, link-local, private
(not allowlisted) or metadata address is refused (``egress_refused``) before the credential is
sent, and an admitted one connects only to the checked address. No response body, header or URL reaches a
caller or a log line; the status class is the only fact kept.

**Backoff.** A ``429`` or ``503`` answer with a ``Retry-After`` of at most
:data:`MAX_RETRY_AFTER_SECONDS` seconds is retried after that wait, at most
:data:`MAX_RETRIES_PER_REQUEST` times per request and within :data:`MAX_BACKOFF_SECONDS_PER_READER`
seconds of waiting per reader (one connector run). Without a usable ``Retry-After``, or beyond the
bounds, the request fails with its fixed reason (``source_rate_limited`` / ``source_unavailable``):
never a tight loop.

**Links.** :meth:`SourceReader.get_link` follows a source's own ``_links.next`` verbatim, relative
to the configured base URL (Confluence Cloud pages by opaque cursor, not by offset). A link must be
a path under ``/rest/api/`` of that base, never another host.
"""

from __future__ import annotations

import asyncio
import email.utils
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from ....oidc_client_credentials import OidcTokenError
from ....outbound_egress import EgressRefusedError
from .connections import SourceConnection
from .contract import (
    REASON_EGRESS_REFUSED,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_NOT_FOUND,
    REASON_SOURCE_RATE_LIMITED,
    REASON_SOURCE_UNAUTHORIZED,
    REASON_SOURCE_UNAVAILABLE,
    ConnectorError,
)
from .egress import source_egress_transport
from .token_errors import reason_for_token_error

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_RETRIES_PER_REQUEST = 2
MAX_RETRY_AFTER_SECONDS = 30.0
MAX_BACKOFF_SECONDS_PER_READER = 120.0
MAX_LINK_CHARS = 2000
_RETRYABLE = (429, 503)


def reason_for_status(status: int) -> str:
    """The fixed reason of a non-200 answer from a source system."""
    if status in (401, 403):
        return REASON_SOURCE_UNAUTHORIZED
    if status == 404:
        return REASON_SOURCE_NOT_FOUND
    if status == 429:
        return REASON_SOURCE_RATE_LIMITED
    if status >= 500:
        return REASON_SOURCE_UNAVAILABLE
    return REASON_SOURCE_CONTRACT_VIOLATION


def retry_after_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    """Seconds from a ``Retry-After`` header (delta seconds or an HTTP date); ``None`` when unusable."""
    text = (value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return float(int(text))
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


#: The one POST path: Jira Cloud's read-only search (``POST /rest/api/3/search/jql``).
JIRA_SEARCH_JQL_PATH = "/rest/api/3/search/jql"


class SourceReader:
    """One read-only HTTP client bound to a connection's base URL and credential."""

    def __init__(
        self,
        connection: SourceConnection,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._connection = connection
        self._transport = transport
        self._timeout = timeout_seconds
        self._backoff_spent = 0.0

    @property
    def base_url(self) -> str:
        return self._connection.base_url

    def _context_path(self) -> str:
        return urlsplit(self._connection.base_url).path.rstrip("/")

    async def get_link(self, link: object) -> dict[str, Any]:
        """Follow a source's ``_links.next`` verbatim, relative to the base URL (optionally context-prefixed)."""
        if type(link) is not str or not link or len(link) > MAX_LINK_CHARS:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        context = self._context_path()
        path = link[len(context):] if context and link.startswith(f"{context}/rest/") else link
        route = path.split("?", 1)[0]  # an opaque cursor in the query may itself contain slashes
        if not route.startswith("/rest/api/") or "//" in route or "\\" in route or ".." in route:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return await self.get_json(path)

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request_json("GET", path, params=params)

    async def post_search_jql(self, body: dict[str, Any]) -> dict[str, Any]:
        """Jira Cloud's read-only issue search, the only POST a sync sends (same governed path as a GET)."""
        if not isinstance(body, dict):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return await self._request_json("POST", JIRA_SEARCH_JQL_PATH, body=body)

    async def _request_json(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not path.startswith("/"):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        url = f"{self._connection.base_url}{path}"
        retries = 0
        while True:
            response = await self._send(method, url, params, body)
            if response.status_code in _RETRYABLE and retries < MAX_RETRIES_PER_REQUEST:
                wait = retry_after_seconds(response.headers.get("Retry-After"))
                if (
                    wait is not None
                    and wait <= MAX_RETRY_AFTER_SECONDS
                    and self._backoff_spent + wait <= MAX_BACKOFF_SECONDS_PER_READER
                ):
                    retries += 1
                    self._backoff_spent += wait
                    await _sleep(wait)
                    continue
            break
        if response.status_code != 200:
            raise ConnectorError(reason_for_status(response.status_code))
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        try:
            payload = response.json()
        except ValueError:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
        if not isinstance(payload, dict):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return payload

    async def _send(
        self, method: str, url: str, params: dict[str, Any] | None, body: dict[str, Any] | None
    ) -> httpx.Response:
        # Only the fixed search path (exactly, under the connection's context path) may be POSTed; anything
        # else is a contract violation, never sent.
        search_path = f"{self._context_path()}{JIRA_SEARCH_JQL_PATH}"
        if method != "GET" and not (method == "POST" and urlsplit(url).path == search_path):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        transport = source_egress_transport(
            self._connection.kind, inner=self._transport, verify=getattr(self._connection, "verify", True) is not False
        )
        headers = self._connection.auth_headers()
        auth = self._connection.http_auth(self._transport)  # client credentials, else None
        try:
            async with httpx.AsyncClient(
                transport=transport, timeout=self._timeout, follow_redirects=False, auth=auth
            ) as client:
                if method == "POST":
                    return await client.post(url, json=body, headers={**headers, "Content-Type": "application/json"})
                return await client.get(url, params=params, headers=headers)
        except OidcTokenError as error:
            raise ConnectorError(reason_for_token_error(error)) from None
        except EgressRefusedError:
            raise ConnectorError(REASON_EGRESS_REFUSED) from None
        except httpx.HTTPError:
            raise ConnectorError(REASON_SOURCE_UNAVAILABLE) from None


__all__ = ["JIRA_SEARCH_JQL_PATH", "SourceReader", "reason_for_status", "retry_after_seconds"]
