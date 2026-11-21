"""GitHub Copilot provider – OAuth + Chat API."""

import json
import os
import subprocess
from pathlib import Path
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

COPILOT_API_MODEL_IDS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-3.5-turbo",
]


def _debug_dump_request(*, messages: list[dict], model: str, tools: list[dict] | None) -> None:
    """Explicit opt-in request dump for loop diagnostics.

    Set OCTRYX_LLM_DEBUG_DUMP_DIR to capture EXACTLY what the model
    receives (messages + offered tool names) per call. Never on by default.
    """
    dump_dir = os.environ.get("OCTRYX_LLM_DEBUG_DUMP_DIR", "").strip()
    if not dump_dir:
        return
    try:
        from ...time_utils import utc_now

        target = Path(dump_dir)
        target.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%H%M%S_%f")
        payload = {
            "model": model,
            "tool_names": [
                (tool.get("function") or {}).get("name") for tool in (tools or [])
            ],
            "messages": messages,
        }
        (target / f"copilot-{stamp}.json").write_text(
            json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 - diagnostics must never break the call
        pass


def _status_error_class(status_code: int, *, error_code: str = "") -> str:
    """Deterministic HTTP status code to runtime error class mapping."""
    if status_code == 408:
        return RUNTIME_ERROR_TIMEOUT
    if status_code == 429 or status_code >= 500:
        return RUNTIME_ERROR_TRANSIENT
    if status_code == 400 and error_code == "model_not_supported":
        # Copilot can return model_not_supported transiently for a model that
        # otherwise serves the same request. Classifying it permanent
        # makes the engine fall straight back to a weaker runtime; transient lets the
        # retry policy try the same runtime again first.
        return RUNTIME_ERROR_TRANSIENT
    return RUNTIME_ERROR_PERMANENT


class CopilotRuntimeError(ProviderRuntimeError, RuntimeError):
    """Copilot API error with an explicit runtime error class.

    Also derives from RuntimeError to preserve the existing exception contract
    for callers that catch RuntimeError around Copilot API calls.
    """


class CopilotClient(BaseLLMProvider):
    name = "copilot"
    API_URL = "https://api.githubcopilot.com"

    def __init__(self, access_token: str | None = None, base_url: str | None = None):
        resolved_access_token = access_token or self.discover_access_token()
        if not resolved_access_token:
            raise ValueError("Copilot provider requires copilot_token or a local Copilot CLI / GitHub auth session")

        api_url = str(base_url or self.API_URL).strip().rstrip("/") or self.API_URL
        self.access_token = resolved_access_token
        self.api_url = api_url
        self.client = httpx.AsyncClient(
            base_url=api_url,
            headers={
                "Authorization": f"Bearer {resolved_access_token}",
                "Content-Type": "application/json",
                "Copilot-Integration-Id": "vscode-chat",
                "Editor-Version": "octryx/0.0.1-alpha",
                "Editor-Plugin-Version": "octryx/0.0.1-alpha",
            },
            timeout=120.0,
        )

    @classmethod
    def discover_access_token(cls) -> str | None:
        for env_name in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
            value = os.getenv(env_name)
            if value:
                return value.strip()

        login_state = cls.read_cli_login_state()
        login = login_state.get("login")
        host = login_state.get("host", "https://github.com")
        if login:
            token = cls.read_macos_keychain_token(f"{host}:{login}")
            if token:
                return token

        return cls.read_macos_keychain_token()

    @staticmethod
    def read_cli_login_state() -> dict[str, str]:
        config_path = Path.home() / ".copilot" / "config.json"
        if not config_path.exists():
            return {}

        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        login_state = data.get("last_logged_in_user") or {}
        login = login_state.get("login")
        host = login_state.get("host")
        model = data.get("model")
        result: dict[str, str] = {}
        if login:
            result["login"] = login
        if host:
            result["host"] = host
        if model:
            result["model"] = model
        return result

    @classmethod
    def detect_auth_session(cls) -> dict[str, str | bool]:
        login_state = cls.read_cli_login_state()
        token = cls.discover_access_token()
        return {
            "available": bool(token),
            "login": login_state.get("login", ""),
            "host": login_state.get("host", "https://github.com"),
            "model": login_state.get("model", ""),
            "source": "copilot-cli" if token else "",
            "auth_type": "oauth" if token else "",
        }

    @staticmethod
    def read_macos_keychain_token(account: str | None = None) -> str | None:
        if os.uname().sysname != "Darwin":
            return None

        cmd = ["security", "find-generic-password", "-s", "copilot-cli", "-w"]
        if account:
            cmd.extend(["-a", account])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

        if result.returncode != 0:
            return None

        token = result.stdout.strip()
        return token or None

    @classmethod
    async def from_oauth_code(cls, code: str, client_id: str, client_secret: str) -> "CopilotClient":
        """Create client from OAuth authorization code."""
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            access_token = data["access_token"]
            return cls(access_token)

    @classmethod
    async def from_refresh_token(cls, refresh_token: str, client_id: str, client_secret: str) -> "CopilotClient":
        """Create client from OAuth refresh token."""
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            access_token = data["access_token"]
            return cls(access_token)

    async def chat(
        self,
        messages: list[dict],
        model: str = "gpt-4o",
        tools: list[dict] | None = None,
        temperature: float = 0,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        _debug_dump_request(messages=messages, model=model, tools=tools)
        if self._uses_responses_api(model):
            return await self._chat_responses(
                messages=messages,
                model=model,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )

        copilot_messages = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": copilot_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        body = final_body(payload)
        with translate_transport_errors("Copilot API"):
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
        try:
            response = await self.client.get("/models")
            if response.status_code == 200:
                data = response.json()
                raw = data.get("data") or data if isinstance(data, list) else []
                if raw:
                    models = []
                    for m in raw:
                        model_id = m.get("id") or m.get("name") or str(m)
                        name = m.get("name") or model_id
                        supports_tools = bool(
                            m.get("capabilities", {}).get("supports_tool_calls") or m.get("supports_tool_calls", False)
                        )
                        context_length = m.get("context_window") or m.get("context_length") or None
                        models.append(
                            {
                                "id": model_id,
                                "name": name,
                                "provider": "copilot",
                                "supports_tools": supports_tools,
                                "context_length": context_length,
                            }
                        )
                    return models
        except (httpx.HTTPError, RuntimeError, ValueError, TypeError):
            pass
        # Fallback to static list
        local_state = self.read_cli_login_state()
        default_model = local_state.get("model")
        models = []
        for model_id in COPILOT_API_MODEL_IDS:
            label = model_id
            if model_id == default_model:
                label = f"{model_id} (CLI default)"
            models.append({"id": model_id, "name": label, "provider": "copilot"})
        return models

    async def close(self):
        await self.client.aclose()

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._extract_error_detail(response)
            message = f"Copilot API error {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise CopilotRuntimeError(
                message,
                error_class=_status_error_class(
                    response.status_code,
                    error_code=self._extract_error_code(response),
                ),
                status_code=response.status_code,
            ) from exc

    def _extract_error_code(self, response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            return str(error.get("code") or "").strip()
        return ""

    def _extract_error_detail(self, response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text[:500].strip()

        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code") or "").strip()
            message = str(error.get("message") or "").strip()
            if code and message:
                return f"{code}: {message}"
            return message or code
        if isinstance(error, str):
            return error.strip()
        return ""

    def _uses_responses_api(self, model: str) -> bool:
        normalized_model = (model or "").lower()
        return normalized_model.startswith("gpt-5") or "codex" in normalized_model

    async def _chat_responses(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None,
        temperature: float,
        max_tokens: int,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "input": self._convert_messages_to_responses_input(messages),
            "max_output_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = self._convert_tools_to_responses_format(tools)
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        if temperature:
            payload["temperature"] = temperature

        body = final_body(payload)
        with translate_transport_errors("Copilot API"):
            response = await self.client.post(
                "/v1/responses", content=body, headers={"Openai-Intent": "conversation-edits", **JSON_HEADERS}
            )
        self._raise_for_status(response)
        data = response.json()
        raw_usage = data.get("usage", {}) or {}
        usage = {
            "prompt_tokens": raw_usage.get("input_tokens", 0),
            "completion_tokens": raw_usage.get("output_tokens", 0),
            "total_tokens": raw_usage.get("total_tokens", 0),
            **raw_usage,
        }
        return {
            "content": self._extract_responses_text(data),
            "tool_calls": self._extract_responses_tool_calls(data),
            "usage": usage,
            "model": data.get("model", model),
        }

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        converted = []
        for msg in messages:
            entry = {"role": msg["role"], "content": msg.get("content", "")}
            if msg.get("tool_calls"):
                entry["tool_calls"] = msg["tool_calls"]
            if msg.get("tool_call_id"):
                entry["tool_call_id"] = msg["tool_call_id"]
            converted.append(entry)
        return converted

    def _convert_messages_to_responses_input(self, messages: list[dict]) -> list[dict]:
        converted = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "tool":
                converted.append(
                    {
                        "type": "function_call_output",
                        "call_id": msg.get("tool_call_id") or msg.get("id") or "",
                        "output": content or "",
                    }
                )
                continue

            tool_calls = msg.get("tool_calls") or []
            if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
                if str(content or "").strip():
                    converted.append(
                        {
                            "role": role,
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": str(content or ""),
                                }
                            ],
                        }
                    )
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function") or {}
                    converted.append(
                        {
                            "type": "function_call",
                            "call_id": tool_call.get("id") or function.get("call_id") or "",
                            "name": function.get("name") or "",
                            "arguments": function.get("arguments") or "{}",
                        }
                    )
                continue

            if isinstance(content, list):
                converted.append({"role": role, "content": content})
                continue
            text_type = "output_text" if role == "assistant" else "input_text"
            converted.append(
                {
                    "role": role,
                    "content": [
                        {
                            "type": text_type,
                            "text": content or "",
                        }
                    ],
                }
            )
        return converted

    def _extract_responses_text(self, data: dict[str, Any]) -> str:
        chunks: list[str] = []
        for item in data.get("output", []) or []:
            for part in item.get("content", []) or []:
                text = part.get("text")
                if text:
                    chunks.append(text)
        return "\n".join(chunk for chunk in chunks if chunk).strip()

    def _extract_responses_tool_calls(self, data: dict[str, Any]) -> list[dict] | None:
        tool_calls = []
        for item in data.get("output", []) or []:
            if item.get("type") == "function_call":
                tool_calls.append(
                    {
                        "id": item.get("call_id") or item.get("id"),
                        "type": "function",
                        "function": {
                            "name": item.get("name"),
                            "arguments": item.get("arguments") or "{}",
                        },
                    }
                )
        return tool_calls or None

    def _convert_tools_to_responses_format(self, tools: list[dict]) -> list[dict]:
        converted = []
        for tool in tools:
            if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
                function = tool["function"]
                converted.append(
                    {
                        "type": "function",
                        "name": function.get("name"),
                        "description": function.get("description", ""),
                        "parameters": self._normalize_schema(
                            function.get("parameters", {"type": "object", "properties": {}})
                        ),
                        "strict": False,
                    }
                )
            else:
                converted.append(tool)
        return converted

    def _normalize_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(schema or {})
        schema_type = normalized.get("type")
        if schema_type == "object":
            normalized.setdefault("properties", {})
            normalized["properties"] = {
                key: self._normalize_schema(value) if isinstance(value, dict) else value
                for key, value in normalized.get("properties", {}).items()
            }
            normalized.setdefault("additionalProperties", False)
        elif schema_type == "array" and isinstance(normalized.get("items"), dict):
            normalized["items"] = self._normalize_schema(normalized["items"])
        return normalized
