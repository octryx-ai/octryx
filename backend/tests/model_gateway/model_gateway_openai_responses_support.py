"""Shared helpers for the test_model_gateway_openai_responses_* modules."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services.model_gateway.inbound import upstream as inbound_upstream

from .conftest import ALIAS, MODEL_GROUP
from .inbound_gateway_support import gateway_setup  # noqa: F401 - fixture

ROUTE = "/api/v1/model-gateway/openai/v1/responses"


CODEX_SESSION = "0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"


def _sse(payload: dict[str, Any]) -> str:
    return f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n"


def _response(model: str, status: str = "in_progress", **extra: Any) -> dict[str, Any]:
    return {"id": "resp_1", "object": "response", "model": model, "status": status, "output": [], **extra}


USAGE = {"input_tokens": 1200, "input_tokens_details": {"cached_tokens": 200}, "output_tokens": 500,
         "output_tokens_details": {"reasoning_tokens": 120}}


CALL = {"type": "function_call", "id": "fc_9", "call_id": "call_9", "name": "shell", "arguments": "{}"}


def _stream(model: str = MODEL_GROUP, *, model_in_created: bool = True) -> bytes:
    created = _response(model) if model_in_created else {"id": "resp_1", "object": "response",
                                                         "status": "in_progress"}
    return "".join([
        _sse({"type": "response.created", "response": created}),
        _sse({"type": "response.output_item.added", "output_index": 0,
              "item": {"type": "message", "role": "assistant", "content": []}}),
        _sse({"type": "response.output_text.delta", "output_index": 0, "delta": "All tests "}),
        _sse({"type": "response.output_text.delta", "output_index": 0, "delta": "pass."}),
        _sse({"type": "response.output_text.done", "output_index": 0, "text": "All tests pass."}),
        _sse({"type": "response.completed", "response": _response(model, "completed", usage=USAGE)}),
    ]).encode("utf-8")


def _faked_stream(model: str, *, completed: bool = True) -> bytes:
    text = "All tests pass."
    events = [_sse({"type": "response.output_text.delta", "item_id": "resp_1", "output_index": 0,
                    "content_index": 0, "delta": text[i:i + 5]}) for i in range(0, len(text), 5)]
    if completed:
        events.append(_sse({"type": "response.completed", "response": _response(model, "completed", usage=USAGE, output=[
            {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": text, "annotations": []}]}, CALL])}))
    return "".join(events).encode("utf-8")


class FakeResponsesGateway:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.model = MODEL_GROUP
        self.model_in_created = True
        self.faked: str | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if json.loads(request.content).get("stream") is True and self.faked:
            return httpx.Response(200, content=_faked_stream(self.model, completed=self.faked == "complete"),
                                  headers={"content-type": "text/event-stream", "request-id": "req_up_3"})
        if json.loads(request.content).get("stream") is True:
            return httpx.Response(200, content=_stream(self.model, model_in_created=self.model_in_created),
                                  headers={"content-type": "text/event-stream", "request-id": "req_up_1"})
        body = _response(self.model, "completed", usage=USAGE, output=[
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]}, CALL])
        return httpx.Response(200, json=body, headers={"request-id": "req_up_2"})


def _body(*, newest: str = "Now summarize.", stream: bool = True) -> dict[str, Any]:
    return {
        "model": ALIAS,
        "instructions": "You are Codex, a coding agent.",
        "stream": stream,
        "store": False,
        "tools": [{"type": "function", "name": "shell", "parameters": {"type": "object"}}],
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Run the tests."}]},
            {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"},
            {"type": "function_call", "call_id": "call_1", "name": "shell",
             "arguments": json.dumps({"command": ["pytest", "-q"]})},
            {"type": "function_call_output", "call_id": "call_1", "output": "3 passed"},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": newest}]},
        ],
    }


@pytest.fixture
async def responses_setup(gateway_setup, monkeypatch):  # noqa: F811
    _anthropic_fake, build = gateway_setup
    fake = FakeResponsesGateway()
    monkeypatch.setattr(inbound_upstream, "upstream_transport", lambda: httpx.MockTransport(fake.handle))

    async def headers(**kwargs: Any) -> dict[str, str]:
        built = await build(**kwargs)
        return {"Authorization": built["Authorization"], "X-Octryx-Session": built["X-Octryx-Session"],
                "X-Octryx-Workspace": built["X-Octryx-Workspace"], "session-id": CODEX_SESSION,
                "thread-id": CODEX_SESSION}

    return fake, headers
