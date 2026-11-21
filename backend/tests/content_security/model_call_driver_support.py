"""Every registered model driver against a fake transport (no network), for the model-call content tests.

Each harness runs the real driver class; the fake upstream records every request body and answers with the
next :class:`Reply` in the driver's own wire format (answer text, optional reasoning, optional tool call).
``reasoning`` says whether the driver can return model reasoning (``thinking``) at all.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

import app.agent.providers.bedrock as bedrock_module
from app.agent.providers.bedrock import BedrockClient
from app.agent.providers.copilot import CopilotClient
from app.agent.providers.google import GoogleClient
from app.agent.providers.litellm_gateway import LiteLLMGatewayClient
from app.agent.providers.ollama import OllamaClient
from app.agent.providers.openai_compatible import OpenAICompatibleClient
from app.agent.providers.openrouter import OpenRouterClient
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


def _ollama(reply: Reply) -> httpx.Response:
    first: dict[str, Any] = {"role": "assistant", "content": reply.text, "thinking": reply.thinking}
    if reply.tool is not None:
        first["tool_calls"] = [{"function": {"name": reply.tool[0], "arguments": reply.tool[1]}}]
    lines = [{"model": "m", "message": first, "done": False},
             {"model": "m", "message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 1}]
    return httpx.Response(200, content="\n".join(json.dumps(item) for item in lines).encode())


def _gemini(reply: Reply) -> httpx.Response:
    parts: list[dict[str, Any]] = [{"text": reply.text}]
    if reply.tool is not None:
        parts.append({"functionCall": {"name": reply.tool[0], "args": reply.tool[1]}})
    return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}],
                                     "usageMetadata": {"promptTokenCount": 1}})


@dataclass
class _Http:
    """A fake HTTP upstream: records each request body, answers with ``wire(next)``."""

    wire: Callable[[Reply], httpx.Response]
    next: Reply
    bodies: list[str] = field(default_factory=list)

    def client(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content.decode())
        return self.wire(self.next)


@dataclass
class _Converse:
    """A fake ``bedrock-runtime`` client."""

    next: Reply
    bodies: list[str] = field(default_factory=list)

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.bodies.append(json.dumps(kwargs, default=str))
        content: list[dict[str, Any]] = [{"text": self.next.text}]
        if self.next.tool is not None:
            content.append({"toolUse": {"toolUseId": "call-9", "name": self.next.tool[0], "input": self.next.tool[1]}})
        return {"output": {"message": {"content": content}}, "usage": {"inputTokens": 1, "outputTokens": 1},
                "stopReason": "tool_use" if self.next.tool else "end_turn"}


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


def _bedrock(monkeypatch: pytest.MonkeyPatch, reply: Reply) -> Harness:
    async def no_catalog(*_args: Any) -> None:
        return None

    monkeypatch.setattr(bedrock_module, "catalog_inference_types", no_catalog)
    upstream = _Converse(reply)
    driver = BedrockClient(region="eu-central-1")
    driver._client = upstream
    return Harness(driver, "anthropic.claude-3-5-sonnet-20241022-v2:0", False, lambda: upstream.bodies,
                   _setter(upstream))


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


DRIVERS: dict[str, Callable[[pytest.MonkeyPatch, Reply], Harness]] = {
    "litellm_gateway": _litellm,
    "bedrock_api": _bedrock,
    "openrouter_api": _http_driver(lambda: OpenRouterClient("or-test-key"), OpenRouterClient.BASE_URL, _openai,
                                   "anthropic/claude-3.5-sonnet"),
    "copilot_api": _http_driver(lambda: CopilotClient("copilot-test-token"), "https://copilot.test", _openai,
                                "gpt-4o"),
    "ollama": _http_driver(lambda: OllamaClient(base_url="http://ollama.test"), "http://ollama.test", _ollama,
                           "llama3", reasoning=True),
    "gemini_api": _http_driver(lambda: GoogleClient(api_key="gemini-test-key"), GoogleClient.BASE_URL, _gemini,
                               "gemini-2.5-flash"),
    "openai_compatible": _http_driver(lambda: OpenAICompatibleClient(base_url="http://compatible.test"),
                                      "http://compatible.test", _openai, "local-model", reasoning=True),
}
