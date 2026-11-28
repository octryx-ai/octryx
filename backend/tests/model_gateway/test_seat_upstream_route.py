from __future__ import annotations

import httpx
import pytest

from app.services.content_routing.gateway_outcome import GatewayOutcome
from app.services.model_gateway.inbound.codex_seat_relay import send_codex_seat
from app.services.model_gateway.inbound.seat import _send
from app.services.model_gateway.inbound.upstream import REASON_SEAT_UPSTREAM_UNREACHABLE

ANTHROPIC = "https://api.anthropic.com"
CHATGPT = "https://chatgpt.com"


def _client(base: str, error: Exception) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return httpx.AsyncClient(base_url=base, transport=httpx.MockTransport(handler))


async def _claude(error: Exception):
    async with _client(ANTHROPIC, error) as client:
        return await _send(client, "/v1/messages", b"{}", {}, GatewayOutcome())


async def _codex(error: Exception):
    async with _client(CHATGPT, error) as client:
        return await send_codex_seat(client, b"{}", {}, GatewayOutcome())


@pytest.mark.asyncio
@pytest.mark.parametrize("send", [_claude, _codex], ids=["claude_seat", "codex_seat"])
@pytest.mark.parametrize("error", [httpx.ConnectError("no route"), httpx.ConnectTimeout("no answer to connect")],
                         ids=["refused", "connect_timeout"])
async def test_a_missing_route_to_the_seat_provider_is_named_configuration(send, error):
    refused = await send(error)
    assert (refused.state, refused.reason, refused.http_status) == (
        "needs_configuration", REASON_SEAT_UPSTREAM_UNREACHABLE, 503)


@pytest.mark.asyncio
@pytest.mark.parametrize("send", [_claude, _codex], ids=["claude_seat", "codex_seat"])
async def test_a_provider_that_connected_but_stalled_is_still_a_timeout(send):
    refused = await send(httpx.ReadTimeout("slow"))
    assert (refused.reason, refused.http_status) == ("upstream_timeout", 504)
