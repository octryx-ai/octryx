"""HTTP boundary from the inbound route to LiteLLM's Anthropic Messages surface.

The client is built exactly like ``litellm/client.LiteLLMGatewayHttpClient``:
from a validated config only, ``trust_env=False`` plus the governed transport
policy, no redirects, and the virtual key as the only credential. Only
``anthropic-version`` and ``anthropic-beta`` travel from the client request;
its ``Authorization``/``x-api-key`` (the platform token) never leave the
platform.

Upstream failures become fixed refusals. A request the transport could not
deliver (timeout, unreachable) is an :class:`InboundRefusal`; a non-success
answer of the upstream is an :class:`UpstreamAnswer`. The moment the response
headers arrive — before any error body is read or the response is closed — the
caller's ``received`` is told the status: the body crossed the transport, so
the request's content record says ``sent`` (``gateway_outcome``).
The upstream body is never passed through; it is only *compared* for the one
documented code that marks a context-window overflow.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

from ..litellm.config import LiteLLMGatewayConfig
from ..litellm.errors import (
    GATEWAY_STATE_CONFIGURATION_INVALID,
    GATEWAY_STATE_CONTEXT_PRESSURE,
    GATEWAY_STATE_TIMEOUT,
    GATEWAY_STATE_UNAUTHORIZED,
    GATEWAY_STATE_UNREACHABLE,
    gateway_state_for_status,
)
from .refusals import InboundRefusal

MESSAGES_PATH = "/v1/messages"
COUNT_TOKENS_PATH = "/v1/messages/count_tokens"
# LiteLLM's OpenAI Responses surface (the ``/openai`` route for Codex).
RESPONSES_PATH = "/v1/responses"

# Claude Code aborts a stream that stays silent for 300 seconds; the upstream
# read timeout matches it so a long thinking pause is not cut short here first.
STREAM_READ_TIMEOUT_SECONDS = 300.0
# Bound on an upstream error body that is compared (never captured).
MAX_ERROR_BODY_BYTES = 64 * 1024

FORWARDED_REQUEST_HEADERS = ("anthropic-version", "anthropic-beta")
_RELAYED_RESPONSE_HEADERS = frozenset({"retry-after", "x-should-retry", "request-id"})
_RELAYED_RESPONSE_PREFIX = "anthropic-ratelimit-"
_CONTEXT_LENGTH_ERROR_CODE = "context_length_exceeded"

REASON_UPSTREAM_REDIRECTED = "upstream_redirected"
REASON_UPSTREAM_TIMEOUT = "upstream_timeout"
REASON_UPSTREAM_UNREACHABLE = "upstream_unreachable"


@dataclass(frozen=True, slots=True)
class UpstreamAnswer(InboundRefusal):
    """The upstream received the request and answered with a non-success status (a refusal to the client, but the
    request was sent)."""


def upstream_transport() -> httpx.AsyncBaseTransport | None:
    """Transport seam: ``None`` in production (httpx's own), a mock in tests."""

    return None


def build_upstream_client(config: LiteLLMGatewayConfig) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=config.endpoint.base_url,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.virtual_key}"},
        timeout=httpx.Timeout(
            connect=10.0,
            read=max(STREAM_READ_TIMEOUT_SECONDS, config.request_timeout_seconds),
            write=30.0,
            pool=10.0,
        ),
        transport=upstream_transport(),
        **config.transport.httpx_client_kwargs(),
        follow_redirects=False,
    )


def forwarded_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {name: headers[name] for name in FORWARDED_REQUEST_HEADERS if headers.get(name)}


def relayed_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name in _RELAYED_RESPONSE_HEADERS or name.startswith(_RELAYED_RESPONSE_PREFIX)
    }


async def send_upstream(
    client: httpx.AsyncClient,
    *,
    path: str,
    body: bytes,
    headers: Mapping[str, str],
    received: Callable[[int], Awaitable[None]],
) -> httpx.Response | InboundRefusal:
    """Send one request with a streamed response (``received``: told the status when the headers arrive); a refusal
    has closed it."""

    request = client.build_request(
        "POST", upstream_path_for(client, path), content=body, headers=forwarded_request_headers(headers)
    )
    failure = ""
    response: httpx.Response | None = None
    try:
        response = await client.send(request, stream=True)
    except httpx.TimeoutException:
        failure = REASON_UPSTREAM_TIMEOUT
    except httpx.TransportError:
        failure = REASON_UPSTREAM_UNREACHABLE
    if response is None:
        if failure == REASON_UPSTREAM_TIMEOUT:
            return InboundRefusal(GATEWAY_STATE_TIMEOUT, failure, 504)
        return InboundRefusal(GATEWAY_STATE_UNREACHABLE, failure or REASON_UPSTREAM_UNREACHABLE, 502)
    relayed = False
    try:
        await received(response.status_code)
        if response.status_code < 300:
            relayed = True
            return response
        return await _refusal_for_status(response)
    finally:
        if not relayed:
            await response.aclose()


def upstream_path_for(client: httpx.AsyncClient, path: str) -> str:
    base_path = client.base_url.path.rstrip("/")
    return path[len("/v1") :] if base_path.endswith("/v1") else path


async def _compared_error_code(response: httpx.Response) -> str:
    raw = b""
    async for chunk in response.aiter_bytes():
        raw += chunk
        if len(raw) > MAX_ERROR_BODY_BYTES:
            return ""
    try:
        body = json.loads(raw)
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, Mapping) else None
    code = error.get("code") if isinstance(error, Mapping) else None
    return code if isinstance(code, str) else ""


async def _refusal_for_status(response: httpx.Response) -> UpstreamAnswer:
    status = response.status_code
    relayed = relayed_response_headers(response.headers)
    reason = f"upstream_status_{status}"
    if 300 <= status < 400:
        return UpstreamAnswer(GATEWAY_STATE_CONFIGURATION_INVALID, REASON_UPSTREAM_REDIRECTED, 502)
    if status in (401, 403):
        # The platform's own virtual key was refused: a configuration problem the
        # client cannot fix by retrying or by signing in again.
        return UpstreamAnswer(
            GATEWAY_STATE_UNAUTHORIZED,
            reason,
            403,
            hint="The platform's model gateway credential was refused. Ask your Octryx administrator.",
        )
    if status == 400 and await _compared_error_code(response) == _CONTEXT_LENGTH_ERROR_CODE:
        return UpstreamAnswer(
            GATEWAY_STATE_CONTEXT_PRESSURE,
            reason,
            400,
            hint="The prompt is too long for the model's context window. Run /compact and retry.",
        )
    if status in (429, 529) or status >= 500:
        hint = "The model gateway is busy or unavailable; the request can be retried."
        return UpstreamAnswer(gateway_state_for_status(status), reason, status, hint=hint, headers=relayed)
    return UpstreamAnswer(
        gateway_state_for_status(status),
        reason,
        status if status in (400, 404, 413, 422) else 400,
        hint="The model gateway rejected the request.",
        headers=relayed,
    )


__all__ = [
    "COUNT_TOKENS_PATH",
    "FORWARDED_REQUEST_HEADERS",
    "MESSAGES_PATH",
    "RESPONSES_PATH",
    "STREAM_READ_TIMEOUT_SECONDS",
    "UpstreamAnswer",
    "build_upstream_client",
    "forwarded_request_headers",
    "relayed_response_headers",
    "send_upstream",
    "upstream_transport",
]
