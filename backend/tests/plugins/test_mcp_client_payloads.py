"""The MCP client normalizes text, data and unknown items in tool, resource and prompt payloads, and a failed tool call raises a typed, redacted error."""

import asyncio

import pytest

from app.plugins.mcp._payloads import normalize_content_items, normalize_prompt_messages
from app.plugins.mcp.client import MCPClientManager


class _FakeSession:
    def __init__(self, *, tool_result=None, resource_result=None, prompt_result=None):
        self._tool_result = tool_result
        self._resource_result = resource_result
        self._prompt_result = prompt_result
        self.closed = asyncio.Event()

    async def close(self):
        self.closed.set()

    async def call_tool(self, tool_name, arguments):
        return self._tool_result

    async def read_resource(self, uri):
        return self._resource_result

    async def get_prompt(self, prompt_name, arguments):
        return self._prompt_result


class _TextItem:
    def __init__(self, text: str):
        self.text = text


class _DataItem:
    def __init__(self, data):
        self.data = data


class _UnknownItem:
    def __str__(self):
        return "unknown-item"


class _PromptContent:
    def __init__(self, *, text: str | None = None, data=None):
        if text is not None:
            self.text = text
        if data is not None:
            self.data = data


class _PromptMessage:
    def __init__(self, content, role: str | None = None):
        self.content = content
        if role is not None:
            self.role = role


class _ToolResult:
    def __init__(self, content):
        self.content = content


class _ResourceResult:
    def __init__(self, contents):
        self.contents = contents


class _PromptResult:
    def __init__(self, messages):
        self.messages = messages


def test_normalize_payload_helpers_cover_text_data_and_unknown():
    assert normalize_content_items((_TextItem("alpha"), _DataItem({"beta": 2}), _UnknownItem())) == [
        {"type": "text", "text": "alpha"},
        {"type": "data", "data": {"beta": 2}},
        {"type": "unknown", "content": "unknown-item"},
    ]

    assert normalize_prompt_messages(
        (
            _PromptMessage(_PromptContent(text="hello"), role="assistant"),
            _PromptMessage(_PromptContent(data={"answer": 42})),
            _PromptMessage(_UnknownItem()),
        )
    ) == [
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": {"answer": 42}},
        {"role": "user", "content": "unknown-item"},
    ]


@pytest.mark.asyncio
async def test_client_normalizes_tool_resource_and_prompt_payloads():
    manager = MCPClientManager()
    manager._sessions["demo"] = _FakeSession(
        tool_result=_ToolResult((_TextItem("alpha"), _DataItem({"beta": 2}), _UnknownItem())),
        resource_result=_ResourceResult((_TextItem("resource"), _DataItem({"path": "/tmp"}), _UnknownItem())),
        prompt_result=_PromptResult(
            (
                _PromptMessage(_PromptContent(text="hello"), role="assistant"),
                _PromptMessage(_PromptContent(data={"answer": 42})),
                _PromptMessage(_UnknownItem()),
            )
        ),
    )

    assert await manager.call_tool("demo", "tool", {}) == {
        "success": True,
        "content": [
            {"type": "text", "text": "alpha"},
            {"type": "data", "data": {"beta": 2}},
            {"type": "unknown", "content": "unknown-item"},
        ],
    }

    assert await manager.read_resource("demo", "uri://resource") == {
        "success": True,
        "contents": [
            {"type": "text", "text": "resource"},
            {"type": "data", "data": {"path": "/tmp"}},
            {"type": "unknown", "content": "unknown-item"},
        ],
    }

    assert await manager.get_prompt("demo", "prompt", {}) == {
        "success": True,
        "messages": [
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": {"answer": 42}},
            {"role": "user", "content": "unknown-item"},
        ],
    }


@pytest.mark.asyncio
async def test_client_call_tool_exception_is_typed_and_redacted(monkeypatch):
    class ExplodingSession:
        async def call_tool(self, _tool_name, _arguments):
            raise RuntimeError("upstream failed with token=abc1" + "23456789")

    monkeypatch.setattr("app.plugins.mcp.client.MCP_AVAILABLE", True)
    manager = MCPClientManager()
    manager._sessions["demo"] = ExplodingSession()

    result = await manager.call_tool("demo", "tool", {})

    assert result["error"] == "MCP tool execution failed: upstream failed with token=[redacted]"
    assert result["error_category"] == "provider_failure"
    assert result["reason"] == "mcp_tool_exception"
    assert result["mcp_server"] == "demo"
    assert result["mcp_tool"] == "tool"
