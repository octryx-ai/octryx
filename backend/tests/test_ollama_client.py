import json

import httpx
import pytest

from app.agent.core.runtime.runtime_errors import ProviderRuntimeError
from app.agent.providers import OllamaClient

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


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


class _FakeAsyncClient:
    def __init__(self):
        self.last_path = ""
        self.last_json = None

    def stream(self, method, path, content, headers=None):
        assert method == "POST"
        self.last_path = path
        self.last_json = json.loads(content)
        return _FakeStreamContext(
            _FakeStreamResponse(
                [
                    (
                        '{"model":"gemma4:e4b","message":{"role":"assistant","content":"","thinking":"Plan"},'
                        '"done":false}'
                    ),
                    (
                        '{"model":"gemma4:e4b","message":{"role":"assistant","content":"Hallo","thinking":""},'
                        '"done":false}'
                    ),
                    (
                        '{"model":"gemma4:e4b","message":{"role":"assistant","content":" Welt","thinking":""},'
                        '"done":false}'
                    ),
                    (
                        '{"model":"gemma4:e4b","message":{"role":"assistant","content":"","tool_calls":'
                        '[{"id":"tool-1"}]},"done":false}'
                    ),
                    (
                        '{"model":"gemma4:e4b","message":{"role":"assistant","content":""},"done":true,'
                        '"prompt_eval_count":12,"eval_count":7}'
                    ),
                ]
            )
        )

    async def aclose(self):
        return None


class _FakePostOnlyClient:
    def __init__(self, payload=None, *, timeout=False):
        self.payload = payload or {}
        self.timeout = timeout

    async def post(self, path, content=None, headers=None):
        if self.timeout:
            raise httpx.ReadTimeout("timed out")
        return _FakeJsonResponse(self.payload)

    async def aclose(self):
        return None


class _FakeJsonResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_ollama_client_streams_and_aggregates_content_and_thinking():
    fake_client = _FakeAsyncClient()
    client = OllamaClient(base_url="http://localhost:11434", config_json={"request_timeout_seconds": 180})
    client.client = fake_client

    response = await client.chat(
        messages=[{"role": "user", "content": "Hallo"}],
        model="gemma4:e4b",
        max_tokens=256,
    )

    assert fake_client.last_path == "/api/chat"
    assert fake_client.last_json["stream"] is True
    assert fake_client.last_json["think"] is False
    assert fake_client.last_json["options"]["num_predict"] == 256
    assert response["content"] == "Hallo Welt"
    assert response["thinking"] == "Plan"
    assert response["tool_calls"] == [{"id": "tool-1"}]


@pytest.mark.asyncio
async def test_ollama_client_ignores_invalid_stream_chunks_when_valid_chunks_exist():
    fake_client = _FakeAsyncClient()

    def broken_stream(method, path, content, headers=None):
        assert method == "POST"
        return _FakeStreamContext(
            _FakeStreamResponse(
                [
                    '{"model":"gemma4:e4b","message":{"role":"assistant","content":"Hallo"},"done":false}',
                    '{"not-valid"',
                    (
                        '{"model":"gemma4:e4b","message":{"role":"assistant","content":" Welt"},"done":true,'
                        '"prompt_eval_count":12,"eval_count":7}'
                    ),
                ]
            )
        )

    fake_client.stream = broken_stream
    client = OllamaClient(base_url="http://localhost:11434", config_json={"request_timeout_seconds": 180})
    client.client = fake_client

    response = await client.chat(
        messages=[{"role": "user", "content": "Hallo"}],
        model="gemma4:e4b",
        max_tokens=256,
    )

    assert response["content"] == "Hallo Welt"
    assert response["usage"]["invalid_stream_chunks"] == 1


@pytest.mark.asyncio
async def test_ollama_client_non_stream_rejects_missing_message_payload():
    client = OllamaClient(base_url="http://localhost:11434", config_json={"request_timeout_seconds": 180})
    client.client = _FakePostOnlyClient({"model": "gemma4:e4b"})

    with pytest.raises(RuntimeError, match="missing message object"):
        await client.chat(
            messages=[{"role": "user", "content": "Hallo"}],
            model="gemma4:e4b",
            max_tokens=256,
        )


@pytest.mark.asyncio
async def test_ollama_client_non_stream_uses_response_payload_for_usage():
    client = OllamaClient(base_url="http://localhost:11434", config_json={"request_timeout_seconds": 180})
    client.client = _FakePostOnlyClient(
        {
            "model": "gemma4:e4b",
            "message": {"role": "assistant", "content": "Hallo Welt", "thinking": "Plan"},
            "prompt_eval_count": 12,
            "eval_count": 7,
            "done_reason": "stop",
        }
    )

    response = await client.chat(
        messages=[{"role": "user", "content": "Hallo"}],
        model="gemma4:e4b",
        max_tokens=256,
    )

    assert response["content"] == "Hallo Welt"
    assert response["thinking"] == "Plan"
    assert response["usage"]["prompt_tokens"] == 12
    assert response["usage"]["completion_tokens"] == 7
    assert response["usage"]["done_reason"] == "stop"


@pytest.mark.asyncio
async def test_ollama_client_surfaces_timeout_error():
    client = OllamaClient(base_url="http://localhost:11434", config_json={"request_timeout_seconds": 180})
    client.client = _FakePostOnlyClient(timeout=True)

    with pytest.raises(ProviderRuntimeError, match=r"Ollama API transport failure \(ReadTimeout\)") as excinfo:
        await client.chat(
            messages=[{"role": "user", "content": "Hallo"}],
            model="gemma4:e4b",
            max_tokens=256,
        )
    assert excinfo.value.runtime_error_class == "timeout"
    assert excinfo.value.runtime_error_class_source == "exception_type"
