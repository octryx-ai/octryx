"""The HTTP leg of a custom REST call: pinned egress, redirects on the same host only, a bounded GET retry.

- The client's transport is the pinned ``custom_rest`` egress transport (``outbound_egress``): ``public_only``, an
  on-prem API only through the admin's private-host allowlist, every request and redirect hop checked once and
  connected only to the checked address. Environment proxies are never read.
- Redirects are followed here, not by ``httpx``: only to the same host and port, so a redirect can never carry the
  technical account's credentials to another host.
- Retries on 429 and 503, at most twice, after ``Retry-After`` (bounded by the call's timeout), only for a call the
  executor says may be repeated (``common.retry_allowed``): GET/HEAD, and PUT/DELETE an admin marked idempotent. A
  POST or PATCH is never sent twice: a 503 after the server already wrote would write again.
"""

from __future__ import annotations

import asyncio
import email.utils
import time
from typing import Any

import httpx

from ..outbound_egress import CONNECTION_CUSTOM_REST, egress_transport

MAX_REDIRECTS = 5
MAX_RETRIES = 2
RETRY_STATUSES = frozenset({429, 503})
_RETRYABLE_METHODS = frozenset({"GET", "HEAD"})


class RedirectRefusedError(httpx.HTTPError):
    """A redirect to another host, or too many hops; nothing was sent there."""


def rest_client(timeout: float) -> httpx.AsyncClient:
    """The client of one call; tests replace it to answer through the real pinned transport."""
    return httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, trust_env=False, transport=egress_transport(CONNECTION_CUSTOM_REST)
    )


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def retry_after_seconds(response: httpx.Response, *, cap: float) -> float:
    raw = str(response.headers.get("retry-after") or "").strip()
    seconds = 1.0
    if raw.isdigit():
        seconds = float(raw)
    elif raw:
        parsed = email.utils.parsedate_to_datetime(raw) if raw else None
        if parsed is not None:
            seconds = max(0.0, parsed.timestamp() - time.time())
    return max(0.0, min(seconds, cap))


def _same_origin(first: httpx.URL, second: httpx.URL) -> bool:
    return first.host == second.host and first.port == second.port and first.scheme == second.scheme


async def _send_following(client: httpx.AsyncClient, request: httpx.Request) -> httpx.Response:
    origin = request.url
    for _ in range(MAX_REDIRECTS + 1):
        response = await client.send(request)
        if not response.is_redirect:
            return response
        location = response.headers.get("location") or ""
        target = request.url.join(location)
        await response.aclose()
        if not _same_origin(origin, target):
            raise RedirectRefusedError("redirect_to_other_host")
        method = "GET" if response.status_code == 303 else request.method
        content = None if method == "GET" else request.content
        request = client.build_request(method, target, headers=request.headers, content=content)
    raise RedirectRefusedError("too_many_redirects")


async def send(client: httpx.AsyncClient, request: httpx.Request, *, timeout: float,
               retryable: bool | None = None) -> tuple[httpx.Response, int]:
    """The final response and how many retries it took (``retryable`` default: GET/HEAD only)."""
    may_retry = request.method in _RETRYABLE_METHODS if retryable is None else retryable
    retries = 0
    while True:
        response = await _send_following(client, request)
        if may_retry and response.status_code in RETRY_STATUSES and retries < MAX_RETRIES:
            await _sleep(retry_after_seconds(response, cap=timeout))
            retries += 1
            continue
        return response, retries


def response_json(response: httpx.Response) -> Any:
    """The parsed JSON body, or the text when the API did not answer JSON (``None`` for an empty body)."""
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


__all__ = ["MAX_RETRIES", "RedirectRefusedError", "response_json", "rest_client", "retry_after_seconds", "send"]
