import httpx
import pytest

from app.agent.core.runtime.runtime_errors import ProviderRuntimeError
from app.agent.engine import _chat_with_runtime_fallback
from app.agent.providers import GoogleClient, OllamaClient, OpenAICompatibleClient

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


class _FakeJsonResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakePostClient:
    def __init__(self, payload):
        self._payload = payload

    async def post(self, *args, **kwargs):
        return _FakeJsonResponse(self._payload)


class _FakeTimeoutPostClient:
    def __init__(self, message="timed out"):
        self._message = message

    async def post(self, *args, **kwargs):
        raise httpx.ReadTimeout(self._message)


class _FakeStreamResponse:
    def __init__(self, payload_lines):
        self._payload_lines = payload_lines
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for line in self._payload_lines:
            yield line


class _FakeStreamContext:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeOllamaClient:
    def stream(self, method, path, content, headers=None):
        assert method == "POST"
        assert path == "/api/chat"
        return _FakeStreamContext(
            _FakeStreamResponse(
                [
                    ('{"model":"gemma4:e4b","message":{"role":"assistant","content":"Hallo"},"done":false}'),
                    '["unexpected"]',
                    (
                        '{"model":"gemma4:e4b","message":{"role":"assistant","content":" Welt"},'
                        '"done":true,"prompt_eval_count":12,"eval_count":7}'
                    ),
                ]
            )
        )

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_retries_malformed_response_once_for_single_runtime(monkeypatch):
    call_count = {"count": 0}

    class RetryProvider:
        async def chat(self, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise RuntimeError("OpenAI-compatible API returned invalid response payload: missing choices")
            return {"content": "ok", "tool_calls": [], "usage": {}, "model": kwargs["model"]}

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: RetryProvider())

    response, runtime, attempts = await _chat_with_runtime_fallback(
        [{"provider_name": "openai_compatible", "endpoint_url": "http://healthy.test", "model": "healthy"}],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        request_timeout_seconds=5,
    )

    assert response["content"] == "ok"
    assert runtime["model"] == "healthy"
    assert call_count["count"] == 2
    assert attempts[0]["status"] == "error"
    assert "missing choices" in attempts[0]["error"]
    assert attempts[1]["status"] == "success"


@pytest.mark.asyncio
async def test_openai_compatible_chat_rejects_missing_message_payload():
    client = OpenAICompatibleClient(base_url="http://localhost:8001/v1", api_key="test-key")
    client.client = _FakePostClient({"choices": [{}]})

    with pytest.raises(RuntimeError, match="missing message object"):
        await client.chat(messages=[{"role": "user", "content": "hello"}], model="demo-model")


@pytest.mark.asyncio
async def test_google_chat_rejects_malformed_candidate_payload():
    client = GoogleClient(api_key="gemini-key")
    client.client = _FakePostClient({"candidates": ["broken"]})

    with pytest.raises(RuntimeError, match="malformed candidate"):
        await client.chat(messages=[{"role": "user", "content": "hello"}], model="gemini-2.5-flash")


@pytest.mark.asyncio
async def test_google_chat_rejects_missing_candidates_payload():
    client = GoogleClient(api_key="gemini-key")
    client.client = _FakePostClient({})

    with pytest.raises(RuntimeError, match="missing candidates"):
        await client.chat(messages=[{"role": "user", "content": "hello"}], model="gemini-2.5-flash")


@pytest.mark.asyncio
async def test_openai_compatible_chat_surfaces_timeout_error():
    client = OpenAICompatibleClient(base_url="http://localhost:8001/v1", api_key="test-key")
    client.client = _FakeTimeoutPostClient()

    with pytest.raises(ProviderRuntimeError, match=r"OpenAI-compatible API transport failure \(ReadTimeout\)") as excinfo:
        await client.chat(messages=[{"role": "user", "content": "hello"}], model="demo-model")
    assert excinfo.value.runtime_error_class == "timeout"
    assert excinfo.value.runtime_error_class_source == "exception_type"


@pytest.mark.asyncio
async def test_google_chat_surfaces_timeout_error():
    client = GoogleClient(api_key="gemini-key")
    client.client = _FakeTimeoutPostClient()

    with pytest.raises(ProviderRuntimeError, match=r"Google Gemini API transport failure \(ReadTimeout\)") as excinfo:
        await client.chat(messages=[{"role": "user", "content": "hello"}], model="gemini-2.5-flash")
    assert excinfo.value.runtime_error_class == "timeout"
    assert excinfo.value.runtime_error_class_source == "exception_type"


@pytest.mark.asyncio
async def test_ollama_client_ignores_non_object_stream_chunks_when_valid_chunks_exist():
    client = OllamaClient(base_url="http://localhost:11434", config_json={"request_timeout_seconds": 180})
    client.client = _FakeOllamaClient()

    response = await client.chat(
        messages=[{"role": "user", "content": "Hallo"}],
        model="gemma4:e4b",
        max_tokens=256,
    )

    assert response["content"] == "Hallo Welt"
    assert response["usage"]["invalid_stream_chunks"] == 1
