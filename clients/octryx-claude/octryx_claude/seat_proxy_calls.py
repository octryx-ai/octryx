"""The seat proxy's calls beside the relay: Codex's search, and reporting a relayed answer to the platform.

A report the platform cannot take now is retried in the background until shortly before its ticket expires.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .seat_proxy_http import (
    PLATFORM_PREFIX,
    AnswerCapture,
    _Request,
    platform_headers,
    relayed_headers,
    upstream_headers,
    write_error,
    write_whole,
)

logger = logging.getLogger("octryx_claude.codex_seat_proxy")

REPORT_PATH = "/api/v1/model-gateway/openai/seat/report"
SEARCH_ADMIT_PATH = "/api/v1/model-gateway/openai/seat/search-admit"
SEARCH_REPORT_PATH = "/api/v1/model-gateway/openai/seat/search-report"
UPSTREAM_SEARCH_PATH = "/backend-api/codex/alpha/search"
RETRY_STATUSES = frozenset({502, 503, 504})
REPORT_RETRY_SECONDS = 840.0
RETRY_FIRST_DELAY = 2.0
RETRY_MAX_DELAY = 30.0
# Reports still being retried, outside any one proxy: a stopped proxy does not cancel them. In memory only: the
# report travels with the session's seat credential, which is never written to disk.
_RETRYING: set[asyncio.Task] = set()


@dataclass(slots=True)
class _Admitted:
    ticket: str
    body: dict[str, Any]
    notice: str


@dataclass(slots=True)
class _Outcome:
    """What the report says about the answer, filled as it arrives (a stop mid-stream still reports the status)."""

    capture: AnswerCapture
    status: int = 0
    headers: dict[str, str] | None = None
    complete: bool = False


class SeatProxyCalls:
    """Search and reporting of :class:`codex_seat_proxy.SeatProxy` (its ``_platform``, ``_upstream``, ``_clock``
    and ``_sleep`` come from that class)."""

    async def _search(self, writer: asyncio.StreamWriter, request: _Request) -> None:
        """Codex's ``web.run`` search: admitted by the platform (a research phase only, recorded with its commands),
        sent to ChatGPT with the person's login, its status reported. A refusal goes back to Codex unchanged."""
        try:
            async with self._platform() as client:
                answer = await client.post(SEARCH_ADMIT_PATH, content=request.body, headers={
                    **platform_headers(request.headers), "content-type": "application/json"})
        except httpx.HTTPError:
            await write_error(writer, 502, "gateway_unreachable", "seat_search_admit_unreachable",
                              "The platform could not be reached; nothing was searched.")
            return
        if answer.status_code != 200:
            kept = {name: value for name, value in answer.headers.items() if name.startswith(PLATFORM_PREFIX)}
            await write_whole(writer, answer.status_code, answer.content, kept)
            return
        try:
            ticket = str(answer.json()["ticket"])
        except (ValueError, KeyError, TypeError):
            await write_error(writer, 502, "gateway_unreachable", "seat_search_admit_invalid",
                              "The platform's answer was not understood; nothing was searched.")
            return
        status = 0
        try:
            async with self._upstream() as client:
                upstream = await client.post(UPSTREAM_SEARCH_PATH, content=request.body, headers={
                    **upstream_headers(request.headers), "content-type": "application/json"})
            status = upstream.status_code
            await write_whole(writer, upstream.status_code, upstream.content, relayed_headers(upstream.headers))
        except httpx.TimeoutException:
            await write_error(writer, 504, "gateway_timeout", "upstream_timeout", "ChatGPT did not answer.")
        except httpx.HTTPError:
            await write_error(writer, 502, "gateway_unreachable", "upstream_unreachable",
                              "ChatGPT could not be reached from this device.")
        finally:
            with contextlib.suppress(httpx.HTTPError):
                async with self._platform() as client:
                    await client.post(SEARCH_REPORT_PATH, json={"ticket": ticket, "status_code": status},
                                      headers=platform_headers(request.headers))

    async def _report(self, request: _Request, admitted: _Admitted, outcome: _Outcome, *, duration_ms: int) -> None:
        capture = outcome.capture
        payload = {"ticket": admitted.ticket, "body": admitted.body, "status_code": outcome.status,
                   "headers": outcome.headers or {}, "response_b64": base64.b64encode(capture.raw()).decode("ascii"),
                   "truncated": capture.truncated, "complete": outcome.complete, "duration_ms": duration_ms}
        headers = platform_headers(request.headers)
        if await self._report_once(payload, headers):
            return
        # The platform is unavailable: retried in the background until shortly before the ticket expires.
        task = asyncio.get_running_loop().create_task(self._report_later(payload, headers))
        _RETRYING.add(task)
        task.add_done_callback(_RETRYING.discard)

    async def _report_once(self, payload: dict[str, Any], headers: dict[str, str]) -> bool:
        """Sent and answered for good (stored, or refused for a reason a retry cannot change): ``True``."""
        try:
            async with self._platform() as client:
                answer = await client.post(REPORT_PATH, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("Codex seat report failed (error_class=%s)", type(exc).__name__)
            return False
        if answer.status_code in RETRY_STATUSES:
            logger.warning("Codex seat report refused (status=%s), retried", answer.status_code)
            return False
        if answer.status_code != 200:
            logger.warning("Codex seat report refused (status=%s)", answer.status_code)
        return True

    async def _report_later(self, payload: dict[str, Any], headers: dict[str, str]) -> None:
        deadline, delay = self._clock() + REPORT_RETRY_SECONDS, RETRY_FIRST_DELAY
        while self._clock() + delay <= deadline:
            await self._sleep(delay)
            if await self._report_once(payload, headers):
                return
            delay = min(delay * 2, RETRY_MAX_DELAY)
        logger.warning("Codex seat report given up (the platform's sweep marks the call without a report)")
