"""Turn an admitted upstream response into the client response, then record it.

Streaming responses are verified before the client receives a byte: the relay
reads until ``message_start`` has been checked (see ``anthropic_stream``), so a
served-model violation can still be an HTTP error. After that, events are
forwarded as they arrive, with a keep-alive ``ping`` injected when the upstream
is silent (Claude Code aborts a stream after 300 silent seconds, and a Bedrock
upstream sends no pings of its own). Whatever happens afterwards — completion,
upstream failure, or the client disconnecting — the observed usage and
transcript are recorded in a fresh database session under a shielded scope.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

import anyio
import httpx
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..litellm.errors import (
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
    GATEWAY_STATE_TIMEOUT,
    GATEWAY_STATE_UNREACHABLE,
)
from .anthropic_stream import (
    PING_EVENT,
    REASON_MISSING_MESSAGE_START,
    REASON_RESPONSE_NOT_JSON,
    Observation,
    RelayRefused,
    SseRelay,
    relay_json_message,
)
from .refusals import ERROR_TYPE_OVERLOADED, ERROR_TYPE_RATE_LIMIT, InboundRefusal, anthropic_error_response
from .transcript import GatewayCallRecord, record_gateway_call
from .upstream import relayed_response_headers

KEEPALIVE_PING_SECONDS = 20.0
MAX_RESPONSE_BODY_BYTES = 16 * 1024 * 1024
REASON_UPSTREAM_READ_TIMEOUT = "upstream_read_timeout"
REASON_UPSTREAM_READ_FAILED = "upstream_read_failed"
REASON_RESPONSE_TOO_LARGE = "response_body_too_large"

# Builds the call record once the observation is final.
RecordFactory = Callable[[Observation, str, int, str], GatewayCallRecord]
# Renders a refusal in the client's API shape; checks and rewrites a non-streamed answer.
ErrorRenderer = Callable[[InboundRefusal], Response]
JsonAnswer = Callable[[Any, Any, Observation], dict[str, Any]]


class StreamRelay(Protocol):
    """An incremental SSE relay (``anthropic_stream.SseRelay``, ``responses_stream.ResponsesSseRelay``)."""

    observation: Observation

    @property
    def verified(self) -> bool: ...

    def feed(self, chunk: bytes) -> list[bytes]: ...

    def finish(self) -> list[bytes]: ...

_STATUS_FOR_UPSTREAM_ERROR_TYPE = {ERROR_TYPE_RATE_LIMIT: 429, ERROR_TYPE_OVERLOADED: 529}


def refusal_for_relay(exc: RelayRefused, headers: dict[str, str]) -> InboundRefusal:
    if exc.upstream_error_type:
        status = _STATUS_FOR_UPSTREAM_ERROR_TYPE.get(exc.upstream_error_type, 502)
        return InboundRefusal(
            exc.state, exc.reason, status, hint="The model stream failed; the request can be retried.", headers=headers
        )
    # A contract or served-model violation is deterministic for this
    # configuration: tell the client not to retry it.
    return InboundRefusal(
        exc.state,
        exc.reason,
        502,
        hint="The model gateway answered outside its admitted contract; the answer was discarded.",
        headers={**headers, "x-should-retry": "false"},
    )


def _read_failure(exc: httpx.HTTPError, headers: dict[str, str]) -> InboundRefusal:
    """The upstream failed while its answer was read, before the client got any of it."""

    if isinstance(exc, httpx.TimeoutException):
        return InboundRefusal(GATEWAY_STATE_TIMEOUT, REASON_UPSTREAM_READ_TIMEOUT, 504, headers=headers)
    return InboundRefusal(GATEWAY_STATE_UNREACHABLE, REASON_UPSTREAM_READ_FAILED, 502, headers=headers)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def _record(make_record: RecordFactory, observation: Observation, request_id: str, started: float,
                  refused_reason: str = "") -> None:
    await record_gateway_call(make_record(observation, request_id, _elapsed_ms(started), refused_reason))


async def _verified_head(
    relay: SseRelay | StreamRelay, iterator: AsyncIterator[bytes], missing_start_reason: str
) -> list[bytes]:
    """Reads until the relay has checked the served model; what it may forward by then."""
    head: list[bytes] = []
    while not relay.verified:
        try:
            chunk = await iterator.__anext__()
        except StopAsyncIteration:
            head.extend(relay.finish())
            if not relay.verified:
                raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, missing_start_reason) from None
            break
        head.extend(relay.feed(chunk))
    return head


async def _relayed_body(
    response: httpx.Response,
    client: httpx.AsyncClient,
    relay: SseRelay | StreamRelay,
    iterator: AsyncIterator[bytes],
    head: list[bytes],
    *,
    keepalive: bytes,
    started: float,
    request_id: str,
    make_record: RecordFactory,
) -> AsyncIterator[bytes]:
    """The verified head, then the rest as it arrives with keep-alives; recorded whatever ends the stream."""
    pending: asyncio.Future[Any] | None = None
    upstream_ended = False
    try:
        for piece in head:
            yield piece
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_PING_SECONDS)
            if not done:
                yield keepalive
                continue
            task, pending = pending, None
            try:
                chunk = task.result()
            except StopAsyncIteration:
                upstream_ended = True
                break
            for piece in relay.feed(chunk):
                yield piece
        for piece in relay.finish():
            yield piece
    except (RelayRefused, httpx.HTTPError):
        # Mid-stream the status is already sent: the stream ends here and is
        # recorded as incomplete.
        pass
    finally:
        if pending is not None:
            pending.cancel()
        observation = relay.observation
        if upstream_ended and observation.stop_reason and not observation.upstream_error_type:
            # A body ending after a ``message_delta`` with a stop reason is a
            # complete answer even without ``message_stop``.
            observation.stream_completed = True
        with anyio.CancelScope(shield=True):
            await response.aclose()
            await client.aclose()
            await _record(make_record, observation, request_id, started)


async def relay_stream(
    response: httpx.Response,
    client: httpx.AsyncClient,
    relay: SseRelay | StreamRelay,
    *,
    started: float,
    make_record: RecordFactory,
    render: ErrorRenderer = anthropic_error_response,
    keepalive: bytes = PING_EVENT,
    missing_start_reason: str = REASON_MISSING_MESSAGE_START,
) -> Response:
    headers = relayed_response_headers(response.headers)
    request_id = headers.get("request-id", "")
    iterator = response.aiter_bytes()
    head: list[bytes] = []
    refused: InboundRefusal | None = None
    try:
        head = await _verified_head(relay, iterator, missing_start_reason)
    except RelayRefused as exc:
        refused = refusal_for_relay(exc, headers)
    except httpx.HTTPError as exc:
        refused = _read_failure(exc, headers)
    if refused is not None:
        await response.aclose()
        await client.aclose()
        if relay.observation.usage:
            # The upstream already billed the call it started; account for it.
            await _record(make_record, relay.observation, request_id, started, refused.reason)
        return render(refused)
    return StreamingResponse(
        _relayed_body(response, client, relay, iterator, head, keepalive=keepalive, started=started,
                      request_id=request_id, make_record=make_record),
        status_code=response.status_code,
        media_type="text/event-stream",
        headers={**headers, "cache-control": "no-cache"},
    )


async def relay_json(
    response: httpx.Response,
    client: httpx.AsyncClient,
    observation: Observation,
    *,
    entry: Any,
    started: float,
    make_record: RecordFactory,
    render: ErrorRenderer = anthropic_error_response,
    answer: JsonAnswer = relay_json_message,
) -> Response:
    headers = relayed_response_headers(response.headers)
    request_id = headers.get("request-id", "")
    raw = b""
    refused: InboundRefusal | None = None
    try:
        async for chunk in response.aiter_bytes():
            raw += chunk
            if len(raw) > MAX_RESPONSE_BODY_BYTES:
                raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_RESPONSE_TOO_LARGE)
        try:
            parsed = json.loads(raw)
        except ValueError:
            raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_RESPONSE_NOT_JSON) from None
        content = answer(entry, parsed, observation)
    except RelayRefused as exc:
        refused = refusal_for_relay(exc, headers)
    except httpx.HTTPError as exc:
        refused = _read_failure(exc, headers)
    finally:
        await response.aclose()
        await client.aclose()
    if refused is not None:
        if observation.usage:
            await _record(make_record, observation, request_id, started, refused.reason)
        return render(refused)
    await _record(make_record, observation, request_id, started)
    return JSONResponse(status_code=response.status_code, content=content, headers=headers)


__all__ = [
    "KEEPALIVE_PING_SECONDS",
    "MAX_RESPONSE_BODY_BYTES",
    "StreamRelay",
    "refusal_for_relay",
    "relay_json",
    "relay_stream",
]
