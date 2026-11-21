"""Providers raise ProviderRuntimeError with explicit runtime error classes.

These tests simulate HTTP error responses at the provider's httpx client
boundary (same pattern as tests/test_provider_runtime_hardening.py) and assert
the raised exception carries an explicit ``runtime_error_class``, so runtime
error classification no longer depends on error-message wording.
"""

from __future__ import annotations

import httpx
import pytest

from app.agent.core.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_EXPLICIT,
    RUNTIME_ERROR_CONTEXT_PRESSURE,
    RUNTIME_ERROR_MALFORMED_RESPONSE,
    RUNTIME_ERROR_PERMANENT,
    RUNTIME_ERROR_TIMEOUT,
    RUNTIME_ERROR_TRANSIENT,
    ProviderRuntimeError,
    classify_runtime_error,
)
from app.agent.providers import CopilotClient, GoogleClient, OllamaClient, OpenAICompatibleClient, OpenRouterClient
from tests.provider_runtime_error_adoption_support import _MESSAGES

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


def _http_response(status_code: int, *, text: str = "", json_body=None) -> httpx.Response:
    request = httpx.Request("POST", "http://provider.test/chat/completions")
    if json_body is not None:
        return httpx.Response(status_code, json=json_body, request=request)
    return httpx.Response(status_code, text=text, request=request)


class _FakePostClient:
    """Async httpx-client stand-in returning one canned response for post()."""

    def __init__(self, response: httpx.Response):
        self._response = response

    async def post(self, *args, **kwargs):
        return self._response

    async def aclose(self):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_class"),
    [
        (429, RUNTIME_ERROR_TRANSIENT),
        (401, RUNTIME_ERROR_PERMANENT),
        (503, RUNTIME_ERROR_TRANSIENT),
    ],
)
async def test_openrouter_chat_maps_http_status_to_explicit_error_class(status_code, expected_class):
    client = OpenRouterClient(api_key="test-key")
    client.client = _FakePostClient(_http_response(status_code, text="upstream detail"))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="anthropic/claude-3.5-sonnet")

    assert excinfo.value.runtime_error_class == expected_class
    assert excinfo.value.status_code == status_code
    assert f"OpenRouter API error ({status_code})" in str(excinfo.value)
    assert "upstream detail" in str(excinfo.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_class"),
    [
        (429, RUNTIME_ERROR_TRANSIENT),
        (401, RUNTIME_ERROR_PERMANENT),
        (503, RUNTIME_ERROR_TRANSIENT),
        (408, RUNTIME_ERROR_TIMEOUT),
        (500, RUNTIME_ERROR_TRANSIENT),
        (422, RUNTIME_ERROR_PERMANENT),
    ],
)
async def test_openai_compatible_chat_maps_http_status_to_explicit_error_class(status_code, expected_class):
    client = OpenAICompatibleClient(base_url="http://localhost:8001/v1", api_key="test-key")
    client.client = _FakePostClient(_http_response(status_code, text="upstream detail"))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="demo-model")

    assert excinfo.value.runtime_error_class == expected_class
    assert excinfo.value.status_code == status_code
    assert f"OpenAI-compatible API error ({status_code})" in str(excinfo.value)


@pytest.mark.asyncio
async def test_openai_compatible_maps_documented_context_length_code_to_context_pressure():
    body = {
        "error": {
            "code": "context_length_exceeded",
            "message": "This model's maximum context length is exceeded.",
        }
    }
    client = OpenAICompatibleClient(base_url="http://localhost:8001/v1", api_key="test-key")
    client.client = _FakePostClient(_http_response(400, json_body=body))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="demo-model")

    assert excinfo.value.runtime_error_class == RUNTIME_ERROR_CONTEXT_PRESSURE
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_openai_compatible_chat_maps_invalid_json_body_to_malformed_response():
    client = OpenAICompatibleClient(base_url="http://localhost:8001/v1", api_key="test-key")
    client.client = _FakePostClient(_http_response(200, text="not-json"))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="demo-model")

    assert excinfo.value.runtime_error_class == RUNTIME_ERROR_MALFORMED_RESPONSE
    assert "returned invalid JSON" in str(excinfo.value)


@pytest.mark.asyncio
async def test_openai_compatible_splits_inline_think_reasoning_out_of_content():
    # Reasoning models behind OpenAI-compatible gateways (MiniMax M-series,
    # DeepSeek R-series) inline chain-of-thought as <think> blocks — it must
    # land in `thinking`, never in assistant content.
    client = OpenAICompatibleClient(base_url="http://localhost:8001/v1", api_key="test-key")
    client.client = _FakePostClient(
        _http_response(
            200,
            json_body={
                "choices": [
                    {
                        "message": {
                            "content": "<think>User wants a tool call.</think>Calling the tool now.",
                            "tool_calls": [
                                {"id": "c1", "function": {"name": "run_validation_commands", "arguments": "{}"}}
                            ],
                        }
                    }
                ],
                "usage": {},
                "model": "MiniMax-M3",
            },
        )
    )

    result = await client.chat(messages=_MESSAGES, model="MiniMax-M3")
    assert result["content"] == "Calling the tool now."
    assert result["thinking"] == "User wants a tool call."
    assert result["tool_calls"][0]["function"]["name"] == "run_validation_commands"

    # Unterminated block (stream cut-off) must not swallow the visible prefix.
    client.client = _FakePostClient(
        _http_response(
            200,
            json_body={
                "choices": [{"message": {"content": "Done.<think>partial reasoning"}}],
                "usage": {},
                "model": "MiniMax-M3",
            },
        )
    )
    result = await client.chat(messages=_MESSAGES, model="MiniMax-M3")
    assert result["content"] == "Done."
    assert result["thinking"] == "partial reasoning"


@pytest.mark.asyncio
async def test_ollama_chat_maps_http_status_to_explicit_error_class():
    client = OllamaClient(base_url="http://localhost:11434")
    # Fake client has no ``stream`` attribute, so the non-streaming path is used.
    client.client = _FakePostClient(_http_response(500, text="server exploded"))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="gemma3")

    assert excinfo.value.runtime_error_class == RUNTIME_ERROR_TRANSIENT
    assert excinfo.value.status_code == 500
    assert "Ollama API error (500)" in str(excinfo.value)


@pytest.mark.asyncio
async def test_google_chat_maps_http_status_to_explicit_error_class():
    client = GoogleClient(api_key="gemini-key")
    client.client = _FakePostClient(_http_response(429, text="quota exhausted"))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="gemini-2.5-flash")

    assert excinfo.value.runtime_error_class == RUNTIME_ERROR_TRANSIENT
    assert excinfo.value.status_code == 429
    assert "Google Gemini API error (429)" in str(excinfo.value)


@pytest.mark.asyncio
async def test_copilot_chat_maps_http_status_to_explicit_error_class():
    client = CopilotClient(access_token="test-token")
    client.client = _FakePostClient(_http_response(403, text="forbidden"))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="gpt-4o")

    assert excinfo.value.runtime_error_class == RUNTIME_ERROR_PERMANENT
    assert excinfo.value.status_code == 403
    assert "Copilot API error 403" in str(excinfo.value)


@pytest.mark.asyncio
async def test_copilot_flaky_model_not_supported_is_transient():
    # Copilot intermittently 400s model_not_supported for a model that served
    # the previous request; permanent classification would dump runs onto a weaker
    # fallback runtime. Other 400s stay permanent.
    client = CopilotClient(access_token="test-token")
    client.client = _FakePostClient(
        _http_response(
            400,
            json_body={"error": {"code": "model_not_supported", "message": "The requested model is not supported."}},
        )
    )

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="gpt-4o")

    assert excinfo.value.runtime_error_class == RUNTIME_ERROR_TRANSIENT
    assert excinfo.value.status_code == 400

    client.client = _FakePostClient(
        _http_response(400, json_body={"error": {"code": "bad_request", "message": "invalid payload"}})
    )
    with pytest.raises(ProviderRuntimeError) as other:
        await client.chat(messages=_MESSAGES, model="gpt-4o")
    assert other.value.runtime_error_class == RUNTIME_ERROR_PERMANENT


@pytest.mark.asyncio
async def test_provider_http_errors_classify_with_explicit_source():
    client = OpenRouterClient(api_key="test-key")
    client.client = _FakePostClient(_http_response(429, text="rate limited"))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="anthropic/claude-3.5-sonnet")

    classification = classify_runtime_error(excinfo.value)
    assert classification.error_class == RUNTIME_ERROR_TRANSIENT
    assert classification.source == CLASSIFICATION_SOURCE_EXPLICIT


@pytest.mark.asyncio
async def test_openai_compatible_list_models_still_returns_empty_on_http_error():
    client = OpenAICompatibleClient(base_url="http://localhost:8001/v1", api_key="test-key")

    class _FakeGetClient:
        async def get(self, *args, **kwargs):
            return _http_response(503, text="unavailable")

        async def aclose(self):
            return None

    client.client = _FakeGetClient()

    assert await client.list_models() == []
