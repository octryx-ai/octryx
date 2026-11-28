"""The HTTP leg of a custom REST call: pinned egress, redirects on the same host only, a bounded GET retry."""

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
    pass


def rest_client(timeout: float) -> httpx.AsyncClient:
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
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


__all__ = ["MAX_RETRIES", "RedirectRefusedError", "response_json", "rest_client", "retry_after_seconds", "send"]
