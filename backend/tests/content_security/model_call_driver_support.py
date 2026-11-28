"""Every registered model driver, plus a driver without a governed route, against a fake transport (no network)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from app.agent.providers.base import BaseLLMProvider
from app.agent.providers.litellm_gateway import LiteLLMGatewayClient
from app.services.content_security.model_call_outbound import JSON_HEADERS, final_body
from app.services.model_gateway.litellm.capability_evidence import ProbeEvidenceCache
from tests.model_gateway.conftest import (
    ALIAS,
    BASE_URL,
    VIRTUAL_KEY,
    FakeLiteLLMGateway,
    chat_body,
    gateway_config,
    verified_admission,
)


@dataclass(frozen=True)
class Reply:
    text: str
    thinking: str = ""
    tool: tuple[str, dict[str, Any]] | None = None


@dataclass
class Harness:
    driver: Any
    model: str
    reasoning: bool
    sent: Callable[[], list[str]]
    answer: Callable[[Reply], None]


def _openai_tool_calls(reply: Reply) -> list[dict[str, Any]] | None:
    if reply.tool is None:
        return None
    name, args = reply.tool
    return [{"id": "call-9", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]


def _openai(reply: Reply) -> httpx.Response:
    text = f"<think>{reply.thinking}</think>{reply.text}" if reply.thinking else reply.text
    return httpx.Response(200, json={"choices": [{"message": {"content": text, "tool_calls": _openai_tool_calls(reply)}}],
                                     "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "model": "m"})


@dataclass
class _Http:
    wire: Callable[[Reply], httpx.Response]
    next: Reply
    bodies: list[str] = field(default_factory=list)

    def client(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content.decode())
        return self.wire(self.next)


def _setter(target: Any) -> Callable[[Reply], None]:
    def answer(reply: Reply) -> None:
        target.next = reply
    return answer


def _http_driver(build: Callable[[], Any], base_url: str, wire: Callable[[Reply], httpx.Response], model: str,
                 *, reasoning: bool = False) -> Callable[[pytest.MonkeyPatch, Reply], Harness]:
    def make(_monkeypatch: pytest.MonkeyPatch, reply: Reply) -> Harness:
        upstream = _Http(wire, reply)
        driver = build()
        driver.client = upstream.client(base_url)
        return Harness(driver, model, reasoning, lambda: upstream.bodies, _setter(upstream))
    return make


def _litellm(_monkeypatch: pytest.MonkeyPatch, reply: Reply) -> Harness:
    def payload(item: Reply) -> dict[str, Any]:
        return chat_body(choices=[{"message": {"content": item.text, "tool_calls": _openai_tool_calls(item)}}])

    upstream = FakeLiteLLMGateway(chat_payload=payload(reply))
    driver = LiteLLMGatewayClient(endpoint_url=BASE_URL, api_key=VIRTUAL_KEY, config_json=gateway_config(),
                                  transport=upstream.transport(), evidence_cache=ProbeEvidenceCache(),
                                  project_admission=verified_admission(ALIAS, "gpt-4o"))

    def answer(item: Reply) -> None:
        upstream.chat_payload = payload(item)

    return Harness(driver, ALIAS, False, lambda: [item.content.decode() for item in upstream.chat_requests], answer)


# A driver without a governed route (``content_route`` is ``None``): the ``model_call_direct`` point.
class _DirectClient(BaseLLMProvider):

    name = "direct"

    client: httpx.AsyncClient

    async def chat(self, messages: list[dict], model: str, tools: list[dict] | None = None,
                   temperature: float | None = None, max_tokens: int = 4096,
                   reasoning_effort: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if tools:
            payload["tools"] = tools
        response = await self.client.post("/v1/chat/completions", content=final_body(payload), headers=JSON_HEADERS)
        message = response.json()["choices"][0]["message"]
        content = message.get("content") or ""
        thinking = ""
        if content.startswith("<think>") and "</think>" in content:
            thinking, content = content[len("<think>"):].split("</think>", 1)
        return {"content": content, "thinking": thinking, "tool_calls": message.get("tool_calls"),
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "model": model}

    async def list_models(self) -> list[dict]:
        return []

    async def close(self) -> None:
        await self.client.aclose()


DIRECT = "direct"
DIRECT_URL = "http://direct.test"

#: Every registered driver (``provider_registry``) plus ``DIRECT``.
DRIVERS: dict[str, Callable[[pytest.MonkeyPatch, Reply], Harness]] = {
    "litellm_gateway": _litellm,
    DIRECT: _http_driver(_DirectClient, DIRECT_URL, _openai, "local-model", reasoning=True),
}
