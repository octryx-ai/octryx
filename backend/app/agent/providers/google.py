"""Google Gemini provider using Gemini REST API with API key or OAuth access token."""

from __future__ import annotations

import json
import re
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

_FUNCTION_NAME_RE = re.compile(r"[^a-zA-Z0-9_]")


def _status_error_class(status_code: int) -> str:
    """Deterministic HTTP status code to runtime error class mapping."""
    if status_code == 408:
        return RUNTIME_ERROR_TIMEOUT
    if status_code == 429 or status_code >= 500:
        return RUNTIME_ERROR_TRANSIENT
    return RUNTIME_ERROR_PERMANENT


def _sanitize_function_name(name: str) -> str:
    cleaned = _FUNCTION_NAME_RE.sub("_", str(name or "").strip())
    if not cleaned:
        return "tool_call"
    if cleaned[0].isdigit():
        cleaned = f"tool_{cleaned}"
    return cleaned[:64]


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "\n".join(parts)
    return str(content or "")


class GoogleClient(BaseLLMProvider):
    name = "google"
    BASE_URL = "https://generativelanguage.googleapis.com"
    MODEL_FALLBACKS = [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "google", "supports_tools": True},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "provider": "google", "supports_tools": True},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "google", "supports_tools": True},
    ]

    def __init__(
        self,
        api_key: str | None = None,
        access_token: str | None = None,
        project_id: str | None = None,
        request_timeout_seconds: float | None = None,
    ):
        self.api_key = str(api_key or "").strip() or None
        self.access_token = str(access_token or "").strip() or None
        self.project_id = str(project_id or "").strip() or None
        if not self.api_key and not self.access_token:
            raise ValueError("Google provider requires either an API key or an OAuth access token")
        if self.access_token and not self.project_id:
            raise ValueError("Google OAuth provider requires google_cloud_project")
        timeout_seconds = float(request_timeout_seconds or 120.0)
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(connect=10.0, read=max(30.0, timeout_seconds), write=30.0, pool=10.0),
        )

    def _request_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
            headers["x-goog-user-project"] = self.project_id or ""
        return headers

    def _request_params(self) -> dict[str, str]:
        if self.api_key:
            return {"key": self.api_key}
        return {}

    async def chat(
        self,
        messages: list[dict],
        model: str = "gemini-2.5-flash",
        tools: list[dict] | None = None,
        temperature: float = 0,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        system_instruction, contents = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if reasoning_effort:
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": self._thinking_budget(reasoning_effort)}
        if tools:
            payload["tools"] = [{"functionDeclarations": self._convert_tools(tools)}]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        body = final_body(payload)
        with translate_transport_errors("Google Gemini API"):
            response = await self.client.post(
                f"/v1beta/models/{model}:generateContent",
                params=self._request_params(),
                headers={**self._request_headers(), **JSON_HEADERS},
                content=body,
            )
        self._raise_for_status(response)
        data = self._json_dict(response, label="Google Gemini API")
        return self._parse_response(data, model)

    async def list_models(self) -> list[dict]:
        try:
            response = await self.client.get(
                "/v1beta/models",
                params=self._request_params(),
                headers=self._request_headers(),
            )
            self._raise_for_status(response)
            data = self._json_dict(response, label="Google Gemini models API")
            models = []
            for item in data.get("models", []) or []:
                name = str(item.get("name") or "")
                model_id = name.split("/", 1)[-1] if "/" in name else name
                if not model_id:
                    continue
                methods = {str(method) for method in (item.get("supportedGenerationMethods") or [])}
                if "generateContent" not in methods:
                    continue
                input_limit = item.get("inputTokenLimit")
                models.append(
                    {
                        "id": model_id,
                        "name": item.get("displayName") or model_id,
                        "provider": "google",
                        "supports_tools": True,
                        "supports_vision": True,
                        "context_length": input_limit if isinstance(input_limit, int) else None,
                    }
                )
            return models or list(self.MODEL_FALLBACKS)
        except (httpx.HTTPError, ProviderRuntimeError, RuntimeError, ValueError, TypeError):
            return list(self.MODEL_FALLBACKS)

    async def close(self):
        await self.client.aclose()

    @staticmethod
    def _thinking_budget(reasoning_effort: str) -> int:
        normalized = str(reasoning_effort or "").strip().lower()
        if normalized == "high":
            return 2048
        if normalized == "medium":
            return 1024
        if normalized == "low":
            return 256
        return 0

    @staticmethod
    def _raise_for_status(response: httpx.Response):
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            if len(detail) > 500:
                detail = f"{detail[:500]}..."
            raise ProviderRuntimeError(
                f"Google Gemini API error ({response.status_code}): {detail}",
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

    def _convert_messages(self, messages: list[dict]) -> tuple[str, list[dict[str, Any]]]:
        system_chunks: list[str] = []
        contents: list[dict[str, Any]] = []
        tool_name_by_id: dict[str, str] = {}
        for msg in messages:
            role = str(msg.get("role") or "user").strip().lower()
            if role == "system":
                text = _extract_text_content(msg.get("content"))
                if text:
                    system_chunks.append(text)
                continue
            if role == "tool":
                tool_call_id = str(msg.get("tool_call_id") or "").strip()
                tool_name = _sanitize_function_name(tool_name_by_id.get(tool_call_id, "tool_result"))
                content = str(msg.get("content") or "")
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    parsed = {"content": content}
                if not isinstance(parsed, dict):
                    parsed = {"result": parsed}
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": parsed,
                                }
                            }
                        ],
                    }
                )
                continue
            parts: list[dict[str, Any]] = []
            text = _extract_text_content(msg.get("content"))
            if text:
                parts.append({"text": text})
            if role == "assistant" and msg.get("tool_calls"):
                for tool_call in msg.get("tool_calls") or []:
                    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
                    tool_name = _sanitize_function_name(function.get("name") or "")
                    raw_arguments = function.get("arguments")
                    if isinstance(raw_arguments, str):
                        try:
                            arguments = json.loads(raw_arguments)
                        except json.JSONDecodeError:
                            arguments = {"raw": raw_arguments}
                    elif isinstance(raw_arguments, dict):
                        arguments = raw_arguments
                    else:
                        arguments = {}
                    tool_id = str(tool_call.get("id") or "")
                    if tool_id:
                        tool_name_by_id[tool_id] = function.get("name") or tool_name
                    parts.append(
                        {
                            "functionCall": {
                                "name": tool_name,
                                "args": arguments,
                            }
                        }
                    )
            if not parts:
                parts = [{"text": ""}]
            contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        return "\n\n".join(chunk for chunk in system_chunks if chunk), contents

    def _convert_tools(self, tools: list[dict]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function", {}) if isinstance(tool, dict) else {}
            name = _sanitize_function_name(function.get("name") or "")
            if not name:
                continue
            converted.append(
                {
                    "name": name,
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return converted

    def _parse_response(self, data: dict[str, Any], model: str) -> dict[str, Any]:
        prompt_feedback = data.get("promptFeedback")
        candidates = data.get("candidates")
        if candidates is None:
            if isinstance(prompt_feedback, dict):
                block_reason = str(prompt_feedback.get("blockReason") or "").strip()
                if block_reason:
                    raise RuntimeError(f"Google Gemini API blocked response: {block_reason}")
            raise RuntimeError("Google Gemini API returned invalid response payload: missing candidates")
        if not isinstance(candidates, list):
            raise RuntimeError("Google Gemini API returned invalid response payload: malformed candidates")
        content = ""
        tool_calls: list[dict[str, Any]] = []
        if not candidates:
            raise RuntimeError("Google Gemini API returned invalid response payload: missing candidates")
        first_candidate = candidates[0]
        if not isinstance(first_candidate, dict):
            raise RuntimeError("Google Gemini API returned invalid response payload: malformed candidate")
        candidate_content = first_candidate.get("content") or {}
        if not isinstance(candidate_content, dict):
            raise RuntimeError("Google Gemini API returned invalid response payload: malformed content")
        parts = candidate_content.get("parts") or []
        if not isinstance(parts, list):
            raise RuntimeError("Google Gemini API returned invalid response payload: malformed content parts")
        for part in parts:
            if not isinstance(part, dict):
                raise RuntimeError("Google Gemini API returned invalid response payload: malformed content part")
            if isinstance(part.get("text"), str):
                content += part["text"]
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                tool_name = function_call.get("name") or "tool_call"
                args = function_call.get("args")
                if args is None:
                    args = {}
                elif not isinstance(args, dict):
                    raise RuntimeError(
                        "Google Gemini API returned invalid response payload: malformed function call args"
                    )
                tool_calls.append(
                    {
                        "id": f"google-{len(tool_calls) + 1}",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(args),
                        },
                    }
                )
        usage_meta = data.get("usageMetadata") or {}
        return {
            "content": content,
            "tool_calls": tool_calls or None,
            "usage": {
                "prompt_tokens": usage_meta.get("promptTokenCount", 0),
                "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
                "total_tokens": usage_meta.get("totalTokenCount", 0),
            },
            "model": model,
        }
