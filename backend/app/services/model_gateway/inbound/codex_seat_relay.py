"""The Codex seat route's upstream call and the relay of ChatGPT's answer back unchanged (``codex_seat``).

The answer is observed for the transcript (``codex_seat_observer``) and recorded after the response
(``seat_transcript``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping

import anyio
import httpx
from fastapi.responses import Response, StreamingResponse

from ...agent_gateway.contract import STATE_DENIED, STATE_NEEDS_CONFIGURATION
from ...content_routing.gateway_outcome import STAGE_UPSTREAM, GatewayOutcome
from ..litellm.errors import GATEWAY_STATE_TIMEOUT, GATEWAY_STATE_UNREACHABLE
from .anthropic_stream import Observation
from .codex_seat_observer import CodexSeatObserver, observe_responses_body
from .codex_seat_upstream import CODEX_SEAT_RESPONSES_PATH, codex_seat_request_headers
from .refusals import InboundRefusal
from .seat import (
    MAX_SEAT_ERROR_BODY_BYTES,
    MAX_SEAT_JSON_BODY_BYTES,
    REASON_REQUEST_HEADER_INVALID,
    REASON_UPSTREAM_TIMEOUT,
    REASON_UPSTREAM_UNREACHABLE,
    _bounded_bytes,
)
from .seat_transcript import SeatCallRecord, record_seat_call

REASON_CODEX_SEAT_PATH_DENIED = "codex_seat_path_denied"


async def send_codex_seat(client: httpx.AsyncClient, content: bytes, headers: Mapping[str, str],
                          outcome: GatewayOutcome):
    """``content``: the bytes the content decision read; a send that fails before the upstream answers is not a
    content refusal (``GatewayOutcome.stopped``)."""
    try:
        request = client.build_request(
            "POST", CODEX_SEAT_RESPONSES_PATH, content=content,
            headers={**codex_seat_request_headers(headers), "content-type": "application/json"},
        )
    except (UnicodeError, ValueError):
        return outcome.stopped(InboundRefusal(STATE_DENIED, REASON_REQUEST_HEADER_INVALID, 400), STAGE_UPSTREAM)
    if request.url.path != CODEX_SEAT_RESPONSES_PATH:  # the allowlist of one upstream path, checked on the wire URL
        return outcome.stopped(InboundRefusal(STATE_NEEDS_CONFIGURATION, REASON_CODEX_SEAT_PATH_DENIED, 503),
                               STAGE_UPSTREAM)
    try:
        return await client.send(request, stream=True)
    except httpx.TimeoutException:
        return outcome.stopped(InboundRefusal(GATEWAY_STATE_TIMEOUT, REASON_UPSTREAM_TIMEOUT, 504), STAGE_UPSTREAM)
    except httpx.HTTPError:
        return outcome.stopped(InboundRefusal(GATEWAY_STATE_UNREACHABLE, REASON_UPSTREAM_UNREACHABLE, 502),
                               STAGE_UPSTREAM)


async def buffered_codex_answer(
    upstream: httpx.Response, client: httpx.AsyncClient, observation: Observation, headers: dict[str, str],
    make_record: Callable[[], SeatCallRecord],
) -> Response:
    limit = MAX_SEAT_ERROR_BODY_BYTES if upstream.status_code >= 300 else MAX_SEAT_JSON_BODY_BYTES
    try:
        raw = await _bounded_bytes(upstream, limit)
    except httpx.HTTPError:
        raw = b""
    finally:
        await upstream.aclose()
        await client.aclose()
    if upstream.status_code < 300:
        try:
            observe_responses_body(observation, json.loads(raw))
        except ValueError:
            pass
        await record_seat_call(make_record())
    return Response(content=raw, status_code=upstream.status_code, headers=headers)


def streamed_codex_answer(
    upstream: httpx.Response, client: httpx.AsyncClient, observation: Observation, headers: dict[str, str],
    make_record: Callable[[], SeatCallRecord],
) -> Response:
    observer = CodexSeatObserver(observation)
    iterator = upstream.aiter_bytes()

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in iterator:
                observer.feed(chunk)
                yield chunk
            observer.finish()
        except (httpx.HTTPError, asyncio.CancelledError):
            pass  # mid-stream the status is already sent; recorded as incomplete
        finally:
            with anyio.CancelScope(shield=True):
                await upstream.aclose()
                await client.aclose()
                await record_seat_call(make_record())

    return StreamingResponse(stream(), status_code=upstream.status_code, media_type="text/event-stream",
                             headers={**headers, "cache-control": "no-cache"})


__all__ = [
    "REASON_CODEX_SEAT_PATH_DENIED",
    "buffered_codex_answer",
    "send_codex_seat",
    "streamed_codex_answer",
]
