"""A recording fake of ChatGPT's Codex backend, synthetic credentials and request builders for the Codex seat route tests."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest_asyncio

from app.models import SystemConfig
from app.services.agent_gateway.seat_traffic import SEAT_TRAFFIC_GATEWAY, SEAT_TRAFFIC_KEY
from app.services.model_gateway.inbound import codex_seat_upstream
from tests.agent_gateway.seat_presence_support import REGISTER, _gateway_headers, _workspace
from tests.knowledge_evidence_seed_support import seed_member

ROUTE = "/api/v1/model-gateway/openai/seat/responses"


# The person's own ChatGPT access token: never stored, logged, audited or echoed anywhere.
CHATGPT_TOKEN = ("eyJhb" + "GciOiJSUzI1NiJ9.") + "c" * 80 + ".chatgpt-sig"


ACCOUNT = "acct-0f1e2d3c"


CODEX_SESSION = "0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"


CODEX_POLICY = {"codex_seat_mode": "allowed"}


MODEL = "gpt-5-codex"


def _sse(payload: dict[str, Any]) -> str:
    return f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n"


USAGE = {"input_tokens": 1200, "input_tokens_details": {"cached_tokens": 200}, "output_tokens": 500}


CALL = {"type": "function_call", "id": "fc_9", "call_id": "call_9", "name": "shell", "arguments": "{}"}


STREAM = "".join([
    _sse({"type": "response.created", "response": {"id": "resp_1", "model": MODEL, "status": "in_progress"}}),
    _sse({"type": "response.output_text.delta", "output_index": 0, "delta": "All tests "}),
    _sse({"type": "response.output_text.delta", "output_index": 0, "delta": "pass."}),
    _sse({"type": "response.output_item.done", "output_index": 1, "item": CALL}),
    _sse({"type": "response.completed", "response": {"id": "resp_1", "model": MODEL, "status": "completed",
                                                      "usage": USAGE}}),
])


UPSTREAM_HEADERS = {
    "content-type": "text/event-stream", "x-request-id": "req_codex_1", "x-codex-primary-used-percent": "12.5",
    "x-codex-turn-state": "sticky-1", "set-cookie": "__cf_bm=upstream", "x-upstream-internal": "drop-me",
}


class FakeChatGPT:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            error = {"error": {"type": "usage_limit_reached", "message": "The usage limit has been reached"}}
            return httpx.Response(self.status, json=error, headers={"retry-after": "60"})
        return httpx.Response(200, content=STREAM.encode(), headers=UPSTREAM_HEADERS)


@pytest_asyncio.fixture
async def chatgpt(monkeypatch, db) -> FakeChatGPT:
    """ChatGPT's backend, and the platform's ``seat_traffic`` on ``gateway``: these tests prove the relay route
    unchanged (the device's way, the default, is ``test_codex_seat_device``)."""
    fake = FakeChatGPT()
    monkeypatch.setattr(codex_seat_upstream, "codex_seat_transport", lambda: httpx.MockTransport(fake.handle))
    monkeypatch.delenv(codex_seat_upstream.CODEX_SEAT_UPSTREAM_ENV, raising=False)
    db.add(SystemConfig(key=SEAT_TRAFFIC_KEY, value=SEAT_TRAFFIC_GATEWAY))
    await db.commit()
    return fake


async def _register(client, gateway: dict[str, str], engine: str | None = "codex"):
    body: dict[str, Any] = {"profile": "seat", "client": "octryx-codex", "client_version": "0.1.0"}
    if engine:
        body["engine"] = engine
    return await client.post(REGISTER, json=body, headers=gateway)


async def _member(db, *, classification: str | None = "internal", policy: dict | None = None):
    workspace_id = await _workspace(db, classification=classification, policy=policy)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()
    return workspace_id, user_id, await _gateway_headers(db, user_id, workspace_id)


async def _codex_session(client, db, *, policy: dict | None = None):
    workspace_id, user_id, gateway = await _member(db, policy=CODEX_POLICY if policy is None else policy)
    registered = await _register(client, gateway)
    assert registered.status_code == 200, registered.text
    return workspace_id, user_id, gateway, registered.json()["seat_credential"]


def _headers(gateway: dict[str, str], credential: str, **extra: str) -> dict[str, str]:
    return {
        "authorization": f"Bearer {CHATGPT_TOKEN}",
        "chatgpt-account-id": ACCOUNT,
        "openai-beta": "responses=experimental",
        "originator": "codex_cli_rs",
        "session_id": CODEX_SESSION,
        "session-id": CODEX_SESSION,
        "version": "0.99.0",
        "accept": "text/event-stream",
        "x-codex-turn-metadata": '{"workspace":"/Users/someone/repo"}',
        "cookie": "octryx_session=browser-cookie",
        "x-api-key": "should-never-travel",
        "x-octryx-session": gateway["x-octryx-session"],
        "x-octryx-workspace": gateway["x-octryx-workspace"],
        "x-octryx-seat-credential": credential,
        **extra,
    }


def _body(*, newest: str = "Now summarize.", stream: bool = True) -> dict[str, Any]:
    return {
        "model": MODEL,
        "instructions": "You are Codex, a coding agent.",
        "stream": stream,
        "store": False,
        "tools": [{"type": "function", "name": "shell", "parameters": {"type": "object"}},
                  {"type": "namespace", "name": "mcp__docs", "tools": [{"type": "function", "name": "search"}]}],
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Run the tests."}]},
            {"type": "function_call", "call_id": "call_1", "name": "shell",
             "arguments": json.dumps({"command": ["pytest", "-q"]})},
            {"type": "function_call_output", "call_id": "call_1", "output": "3 passed"},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": newest}]},
        ],
    }


def _reason(response: httpx.Response) -> str:
    return response.json()["error"]["code"]
