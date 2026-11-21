"""Copilot client on the Responses API: model routing, empty choices and tool and history conversion."""

import json

import pytest

from app.agent.providers import CopilotClient

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_copilot_client_uses_responses_api_for_codex(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "gpt-5.3-codex",
                "usage": {"input_tokens": 3, "output_tokens": 2},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "OK"}],
                    }
                ],
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def post(self, path, content=None, headers=None):
            captured["path"] = path
            captured["payload"] = json.loads(content)
            captured["headers"] = headers
            return FakeResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr("app.agent.providers.copilot.httpx.AsyncClient", FakeAsyncClient)

    client = CopilotClient("test-token")
    result = await client.chat([{"role": "user", "content": "Reply with OK only."}], model="gpt-5.3-codex")
    await client.close()

    assert captured["path"] == "/v1/responses"
    assert captured["payload"]["model"] == "gpt-5.3-codex"
    assert result["content"] == "OK"
    assert result["usage"]["prompt_tokens"] == 3
    assert result["usage"]["completion_tokens"] == 2


@pytest.mark.asyncio
async def test_copilot_client_uses_responses_api_for_gpt5_family(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "gpt-5.4-mini",
                "usage": {"input_tokens": 3, "output_tokens": 2},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "OK"}],
                    }
                ],
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def post(self, path, content=None, headers=None):
            captured["path"] = path
            captured["payload"] = json.loads(content)
            return FakeResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr("app.agent.providers.copilot.httpx.AsyncClient", FakeAsyncClient)

    client = CopilotClient("test-token")
    result = await client.chat([{"role": "user", "content": "Reply with OK only."}], model="gpt-5.4-mini")
    await client.close()

    assert captured["path"] == "/v1/responses"
    assert captured["payload"]["model"] == "gpt-5.4-mini"
    assert result["content"] == "OK"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_copilot_client_handles_empty_choices(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "claude-haiku-4.5",
                "choices": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def post(self, path, content=None, headers=None):
            return FakeResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr("app.agent.providers.copilot.httpx.AsyncClient", FakeAsyncClient)

    client = CopilotClient("test-token")
    result = await client.chat([{"role": "user", "content": "Reply with OK only."}], model="claude-haiku-4.5")
    await client.close()

    assert result["content"] == ""
    assert result["tool_calls"] is None


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_copilot_client_converts_chat_tools_to_responses_format(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "gpt-5.3-codex",
                "usage": {"input_tokens": 3, "output_tokens": 2},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}],
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def post(self, path, content=None, headers=None):
            captured["payload"] = json.loads(content)
            return FakeResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr("app.agent.providers.copilot.httpx.AsyncClient", FakeAsyncClient)

    client = CopilotClient("test-token")
    await client.chat(
        [{"role": "user", "content": "Reply with OK only."}],
        model="gpt-5.3-codex",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "description": "Return current time",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": True,
                },
            }
        ],
    )
    await client.close()

    assert captured["payload"]["tools"] == [
        {
            "type": "function",
            "name": "get_current_time",
            "description": "Return current time",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            "strict": False,
        }
    ]


def test_copilot_client_converts_tool_history_to_responses_input_items():
    client = CopilotClient("test-token")

    converted = client._convert_messages_to_responses_input(
        [
            {"role": "user", "content": "Call the tool."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "echo_tool", "arguments": '{"text":"hi"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"text":"hi"}'},
            {"role": "user", "content": "Continue."},
        ]
    )

    assert converted == [
        {"role": "user", "content": [{"type": "input_text", "text": "Call the tool."}]},
        {"type": "function_call", "call_id": "call_1", "name": "echo_tool", "arguments": '{"text":"hi"}'},
        {"type": "function_call_output", "call_id": "call_1", "output": '{"text":"hi"}'},
        {"role": "user", "content": [{"type": "input_text", "text": "Continue."}]},
    ]


def test_copilot_client_converts_assistant_text_history_to_responses_output_text():
    client = CopilotClient("test-token")

    converted = client._convert_messages_to_responses_input(
        [
            {"role": "user", "content": "What do you know about Report Builder?"},
            {"role": "assistant", "content": "Report Builder is a reporting utility."},
            {"role": "user", "content": "Be more precise."},
        ]
    )

    assert converted == [
        {"role": "user", "content": [{"type": "input_text", "text": "What do you know about Report Builder?"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "Report Builder is a reporting utility."}]},
        {"role": "user", "content": [{"type": "input_text", "text": "Be more precise."}]},
    ]
