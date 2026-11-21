"""Ollama provider for local model execution."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ...services.content_security.model_call_outbound import JSON_HEADERS, final_body
from ..core.runtime.runtime_errors import (
    RUNTIME_ERROR_MALFORMED_RESPONSE,
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


class OllamaClient(BaseLLMProvider):
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        config_json: dict[str, Any] | None = None,
        request_timeout_seconds: float | None = None,
    ):
        resolved_base_url = str(base_url or "").strip().rstrip("/")
        if not resolved_base_url:
            raise ValueError("Ollama provider requires endpoint_url/base_url")
        self.config_json = config_json if isinstance(config_json, dict) else {}
        timeout_seconds = float(request_timeout_seconds or self.config_json.get("request_timeout_seconds") or 180.0)
        self.client = httpx.AsyncClient(
            base_url=resolved_base_url,
            timeout=httpx.Timeout(connect=10.0, read=max(60.0, timeout_seconds), write=30.0, pool=10.0),
        )

    @staticmethod
    def _invalid_payload(detail: str) -> RuntimeError:
        return RuntimeError(f"Ollama API returned invalid response payload: {detail}")

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            if len(detail) > 500:
                detail = f"{detail[:500]}..."
            raise ProviderRuntimeError(
                f"Ollama API error ({response.status_code}): {detail}",
                error_class=_status_error_class(response.status_code),
                status_code=response.status_code,
            ) from exc

    @staticmethod
    async def _raise_for_stream_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = (await response.aread()).decode("utf-8", errors="replace").strip()
            if len(detail) > 500:
                detail = f"{detail[:500]}..."
            raise ProviderRuntimeError(
                f"Ollama API error ({response.status_code}): {detail}",
                error_class=_status_error_class(response.status_code),
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

    @classmethod
    def _message_dict(cls, payload: dict[str, Any]) -> dict[str, Any]:
        message = payload.get("message")
        if not isinstance(message, dict):
            raise cls._invalid_payload("missing message object")
        return message

    async def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        temperature: float = 0,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        request_think = self.config_json.get("think")
        if request_think is None:
            request_think = False
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": request_think,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        extra_options = self.config_json.get("options")
        if isinstance(extra_options, dict):
            payload["options"].update({str(key): value for key, value in extra_options.items()})
        if tools:
            payload["tools"] = tools
        if reasoning_effort:
            payload["options"]["reasoning_effort"] = reasoning_effort
        if hasattr(self.client, "stream"):
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[dict[str, Any]] | None = None
            response_payload: dict[str, Any] = {}
            invalid_chunk_count = 0
            with translate_transport_errors("Ollama API"):
                body = final_body(payload)
                async with self.client.stream("POST", "/api/chat", content=body, headers=JSON_HEADERS) as response:
                    await self._raise_for_stream_status(response)
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            invalid_chunk_count += 1
                            continue
                        if not isinstance(data, dict):
                            invalid_chunk_count += 1
                            continue
                        response_payload = data
                        message = data.get("message")
                        if not isinstance(message, dict):
                            continue
                        chunk_content = message.get("content", "")
                        if isinstance(chunk_content, str) and chunk_content:
                            content_parts.append(chunk_content)
                        chunk_thinking = message.get("thinking", "")
                        if isinstance(chunk_thinking, str) and chunk_thinking:
                            thinking_parts.append(chunk_thinking)
                        chunk_tool_calls = message.get("tool_calls")
                        if isinstance(chunk_tool_calls, list):
                            tool_calls = chunk_tool_calls
            content = "".join(content_parts)
            thinking = "".join(thinking_parts)
            if not response_payload and invalid_chunk_count:
                raise self._invalid_payload(f"only invalid JSON stream chunks ({invalid_chunk_count})")
        else:
            body = final_body({**payload, "stream": False})
            with translate_transport_errors("Ollama API"):
                response = await self.client.post("/api/chat", content=body, headers=JSON_HEADERS)
            self._raise_for_status(response)
            data = self._json_dict(response, label="Ollama API")
            message = self._message_dict(data)
            content = message.get("content", "") if isinstance(message.get("content"), str) else ""
            thinking = message.get("thinking", "") if isinstance(message.get("thinking"), str) else ""
            tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else None
            response_payload = data
        prompt_eval = int(response_payload.get("prompt_eval_count") or 0)
        eval_count = int(response_payload.get("eval_count") or 0)
        response_model = response_payload.get("model", model)
        return {
            "content": content,
            "tool_calls": tool_calls,
            "usage": {
                "prompt_tokens": prompt_eval,
                "completion_tokens": eval_count,
                "total_tokens": prompt_eval + eval_count,
                "invalid_stream_chunks": invalid_chunk_count if "invalid_chunk_count" in locals() else 0,
                "load_duration_ms": int((response_payload.get("load_duration") or 0) / 1_000_000),
                "prompt_eval_duration_ms": int((response_payload.get("prompt_eval_duration") or 0) / 1_000_000),
                "eval_duration_ms": int((response_payload.get("eval_duration") or 0) / 1_000_000),
                "total_duration_ms": int((response_payload.get("total_duration") or 0) / 1_000_000),
                "done_reason": str(response_payload.get("done_reason") or ""),
            },
            "model": response_model,
            "thinking": thinking,
        }

    async def list_models(self) -> list[dict]:
        try:
            response = await self.client.get("/api/tags")
            self._raise_for_status(response)
            data = response.json()
            models: list[dict] = []
            for item in data.get("models", []) or []:
                model_id = str(item.get("name") or "").strip()
                if not model_id:
                    continue
                models.append(
                    {
                        "id": model_id,
                        "name": model_id,
                        "provider": "ollama",
                        "context_length": ((item.get("details") or {}).get("context_length")),
                        "supports_tools": True,
                    }
                )
            return models
        except (httpx.HTTPError, ProviderRuntimeError, RuntimeError, ValueError, TypeError):
            return []

    async def close(self):
        await self.client.aclose()
