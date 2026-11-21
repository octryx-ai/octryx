"""OpenRouter API client for LLM communication."""

from typing import Any

import httpx

from ...services.content_security.model_call_outbound import JSON_HEADERS, final_body
from ..core.runtime.runtime_errors import (
    RUNTIME_ERROR_PERMANENT,
    RUNTIME_ERROR_TIMEOUT,
    RUNTIME_ERROR_TRANSIENT,
    ProviderRuntimeError,
)
from ..core.runtime.transport_errors import translate_transport_errors
from .base import BaseLLMProvider


def _status_error_class(status_code: int) -> str:
    """Deterministic HTTP status code to runtime error class mapping."""
    if status_code == 408:
        return RUNTIME_ERROR_TIMEOUT
    if status_code == 429 or status_code >= 500:
        return RUNTIME_ERROR_TRANSIENT
    return RUNTIME_ERROR_PERMANENT


class OpenRouterClient(BaseLLMProvider):
    name = "openrouter"
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://octryx.local",
            },
            timeout=120.0,
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response):
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            if len(detail) > 500:
                detail = f"{detail[:500]}..."
            raise ProviderRuntimeError(
                f"OpenRouter API error ({response.status_code}): {detail}",
                error_class=_status_error_class(response.status_code),
                status_code=response.status_code,
            ) from exc

    async def chat(
        self,
        messages: list[dict],
        model: str = "anthropic/claude-3.5-sonnet",
        tools: list[dict] | None = None,
        temperature: float = 0,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}

        body = final_body(payload)
        with translate_transport_errors("OpenRouter API"):
            response = await self.client.post("/chat/completions", content=body, headers=JSON_HEADERS)
        self._raise_for_status(response)
        data = response.json()

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {})

        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls"),
            "usage": data.get("usage", {}),
            "model": data.get("model", model),
        }

    async def list_models(self) -> list[dict]:
        response = await self.client.get("/models")
        self._raise_for_status(response)
        return response.json().get("data", [])

    async def close(self):
        await self.client.aclose()
