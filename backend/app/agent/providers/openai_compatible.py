"""OpenAI-compatible chat client for local and remote gateways."""

from __future__ import annotations

import re
from typing import Any

import httpx

from ...services.content_security.model_call_outbound import JSON_HEADERS, final_body
from ..core.runtime.runtime_errors import (
    RUNTIME_ERROR_CONTEXT_PRESSURE,
    RUNTIME_ERROR_MALFORMED_RESPONSE,
    RUNTIME_ERROR_PERMANENT,
    RUNTIME_ERROR_TIMEOUT,
    RUNTIME_ERROR_TRANSIENT,
    ProviderRuntimeError,
)
from ..core.runtime.transport_errors import translate_transport_errors
from .base import BaseLLMProvider
from .inline_tool_calls import parse_inline_tool_calls
from .sampling_capabilities import sampling_temperature

# Documented OpenAI error code for prompts exceeding the model context window.
_CONTEXT_LENGTH_ERROR_CODE = "context_length_exceeded"

# Reasoning models behind OpenAI-compatible gateways (MiniMax M-series, DeepSeek
# R-series, Qwen thinking variants) inline their chain of thought as
# <think>...</think> blocks in message content. That reasoning must not leak
# into assistant messages or trip the loop's narration guards.
_THINK_BLOCK_PATTERN = re.compile(r"<think>(.*?)</think>\s*", re.DOTALL)


def _split_think_blocks(content: str) -> tuple[str, str]:
    """Split inline <think> reasoning out of content; returns (content, thinking)."""
    if "<think>" not in content:
        return content, ""
    thinking_parts = _THINK_BLOCK_PATTERN.findall(content)
    cleaned = _THINK_BLOCK_PATTERN.sub("", content).strip()
    # An unterminated block (streaming cut-off) hides everything after <think>.
    if "<think>" in cleaned:
        head, _, tail = cleaned.partition("<think>")
        thinking_parts.append(tail)
        cleaned = head.strip()
    return cleaned, "\n\n".join(part.strip() for part in thinking_parts if part.strip())


def _status_error_class(status_code: int) -> str:
    """Deterministic HTTP status code to runtime error class mapping."""
    if status_code == 408:
        return RUNTIME_ERROR_TIMEOUT
    if status_code == 429 or status_code >= 500:
        return RUNTIME_ERROR_TRANSIENT
    return RUNTIME_ERROR_PERMANENT


def _response_error_code(response: httpx.Response) -> str:
    """Extract the structured ``error.code`` field from an error response body."""
    try:
        data = response.json()
    except ValueError:
        return ""
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("code") or "").strip()
    return ""


class OpenAICompatibleClient(BaseLLMProvider):
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        default_headers: dict[str, str] | None = None,
        request_timeout_seconds: float | None = None,
    ):
        resolved_base_url = str(base_url or "").strip().rstrip("/")
        if not resolved_base_url:
            raise ValueError("OpenAI-compatible provider requires endpoint_url/base_url")
        headers = {
            "Content-Type": "application/json",
            **(default_headers or {}),
        }
        token = str(api_key or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.base_url = resolved_base_url
        timeout_seconds = float(request_timeout_seconds or 120.0)
        self.client = httpx.AsyncClient(
            base_url=resolved_base_url,
            headers=headers,
            timeout=httpx.Timeout(connect=10.0, read=max(30.0, timeout_seconds), write=30.0, pool=10.0),
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response, label: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            if len(detail) > 500:
                detail = f"{detail[:500]}..."
            error_class = _status_error_class(response.status_code)
            if _response_error_code(response) == _CONTEXT_LENGTH_ERROR_CODE:
                error_class = RUNTIME_ERROR_CONTEXT_PRESSURE
            raise ProviderRuntimeError(
                f"{label} error ({response.status_code}): {detail}",
                error_class=error_class,
                status_code=response.status_code,
            ) from exc

    @staticmethod
    def _json_dict(response: httpx.Response, *, label: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderRuntimeError(
                f"{label} returned invalid JSON",
                error_class=RUNTIME_ERROR_MALFORMED_RESPONSE,
            ) from exc
        if not isinstance(data, dict):
            raise ProviderRuntimeError(
                f"{label} returned non-object JSON payload",
                error_class=RUNTIME_ERROR_MALFORMED_RESPONSE,
            )
        return data

    async def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        temperature: float = 0,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # Claude 5 behind an OpenAI-compatible endpoint (Anthropic's own) rejects an explicit temperature.
        effective_temperature = sampling_temperature(model, temperature)
        if effective_temperature is not None:
            payload["temperature"] = effective_temperature
        if tools:
            payload["tools"] = tools
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}

        body = final_body(payload)
        with translate_transport_errors("OpenAI-compatible API"):
            response = await self.client.post("/chat/completions", content=body, headers=JSON_HEADERS)
        self._raise_for_status(response, "OpenAI-compatible API")
        data = self._json_dict(response, label="OpenAI-compatible API")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenAI-compatible API returned invalid response payload: missing choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise RuntimeError("OpenAI-compatible API returned invalid response payload: malformed choice")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("OpenAI-compatible API returned invalid response payload: missing message object")
        content = message.get("content", "") if isinstance(message.get("content"), str) else ""
        content, thinking = _split_think_blocks(content)
        native_tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else None
        if not native_tool_calls:
            content, inline_tool_calls = parse_inline_tool_calls(content)
            if inline_tool_calls:
                native_tool_calls = inline_tool_calls
        result: dict[str, Any] = {
            "content": content,
            "tool_calls": native_tool_calls,
            "usage": data.get("usage", {}),
            "model": data.get("model", model),
        }
        if thinking:
            result["thinking"] = thinking
        return result

    async def list_models(self) -> list[dict]:
        try:
            response = await self.client.get("/models")
            self._raise_for_status(response, "OpenAI-compatible models API")
            data = self._json_dict(response, label="OpenAI-compatible models API")
            raw = data.get("data") or []
            return [
                {
                    "id": item.get("id") or item.get("name") or str(item),
                    "name": item.get("name") or item.get("id") or str(item),
                    "provider": "openai_compatible",
                    "context_length": item.get("context_length") or item.get("context_window"),
                    # Generic gateways rarely advertise capabilities. Unknown must
                    # stay None — a hard False makes the engine skip the runtime
                    # for every tool-calling request.
                    "supports_tools": (
                        bool(item["supports_tools"]) if item.get("supports_tools") is not None else None
                    ),
                    "supports_vision": (
                        bool(item["supports_vision"]) if item.get("supports_vision") is not None else None
                    ),
                }
                for item in raw
                if isinstance(item, dict)
            ]
        except (httpx.HTTPError, ProviderRuntimeError, RuntimeError, ValueError, TypeError):
            return []

    async def close(self):
        await self.client.aclose()
