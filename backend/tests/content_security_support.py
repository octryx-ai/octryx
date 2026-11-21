"""A recording provider driver for content-security tests: a real ``BaseLLMProvider`` subclass (so its ``chat``
runs through the model-call enforcement point) that never touches a network."""

from __future__ import annotations

from typing import Any

from app.agent.providers.base import BaseLLMProvider


class RecordingProvider(BaseLLMProvider):
    name = "recording-test"

    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(self, messages: list[dict], model: str, tools: list[dict] | None = None, temperature: float = 0,
                   max_tokens: int = 4096, reasoning_effort: str | None = None) -> dict[str, Any]:
        from app.services.content_security.model_call_outbound import final_body

        final_body({"model": model, "messages": messages, "tools": tools})  # handed to the transport, like a driver
        self.calls.append([dict(item) for item in messages])
        return {"content": self.reply, "tool_calls": None, "model": model,
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}

    async def list_models(self) -> list[dict]:
        return []

    async def close(self) -> None:
        return None


__all__ = ["RecordingProvider"]
