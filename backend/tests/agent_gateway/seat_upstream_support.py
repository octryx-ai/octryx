"""The seat route's fake Anthropic upstream: an ``httpx.MockTransport`` that records every request."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services.model_gateway.inbound import seat_upstream

RATE_LIMITS = {
    "anthropic-ratelimit-unified-5h-utilization": "0.12",
    "anthropic-ratelimit-unified-5h-reset": "1791200000",
    "anthropic-ratelimit-unified-7d-utilization": "0.95",
    "anthropic-ratelimit-unified-7d-reset": "1791600000",
    "anthropic-ratelimit-unified-5h-status": "allowed",
    "anthropic-ratelimit-unified-7d-status": "allowed_warning",
}


def _sse(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


STREAM = "".join([
    _sse("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5", "content": [],
        "usage": {"input_tokens": 40, "output_tokens": 1}}}),
    _sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}),
    _sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "Done."}}),
    _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 9}}),
    _sse("message_stop", {"type": "message_stop"}),
])


class FakeAnthropic:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.headers: dict[str, str] = dict(RATE_LIMITS)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            error = {"type": "error", "error": {"type": "rate_limit_error",
                                                "message": "You've hit your limit · resets 3pm"}}
            return httpx.Response(self.status, json=error, headers=self.headers)
        return httpx.Response(200, content=STREAM.encode(), headers={
            **self.headers, "content-type": "text/event-stream", "request-id": "req_seat_1"})


@pytest.fixture
def anthropic(monkeypatch) -> FakeAnthropic:
    fake = FakeAnthropic()
    monkeypatch.setattr(seat_upstream, "seat_transport", lambda: httpx.MockTransport(fake.handle))
    return fake
