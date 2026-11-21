"""Focused compaction coverage for the additive MCP bridge resource/prompt tools."""

from app.agent.engine import _compact_tool_result_for_model


def test_compact_tool_result_for_model_for_mcp_bridge_resource_and_prompt_tools():
    resources_compact = _compact_tool_result_for_model(
        "list_mcp_server_resources",
        {
            "server_name": "context7",
            "connected": True,
            "search": "react",
            "count": 1,
            "resources": [
                {
                    "uri": "docs://react",
                    "name": "React Docs",
                    "description": "Reference docs",
                    "mime_type": "text/markdown",
                }
            ],
        },
    )
    read_resource_compact = _compact_tool_result_for_model(
        "read_mcp_server_resource",
        {
            "server_name": "context7",
            "uri": "docs://react",
            "success": True,
            "contents": [{"type": "text", "text": "# React"}],
        },
    )
    prompts_compact = _compact_tool_result_for_model(
        "list_mcp_server_prompts",
        {
            "server_name": "context7",
            "connected": True,
            "search": "summary",
            "count": 1,
            "prompts": [
                {
                    "name": "summarize-docs",
                    "description": "Summarize docs",
                    "arguments": [{"name": "topic", "description": "Topic name"}],
                }
            ],
        },
    )
    get_prompt_compact = _compact_tool_result_for_model(
        "get_mcp_server_prompt",
        {
            "server_name": "context7",
            "prompt_name": "summarize-docs",
            "success": True,
            "messages": [{"role": "user", "content": "Summarize react"}],
        },
    )

    assert resources_compact["resources"][0]["uri"] == "docs://react"
    assert read_resource_compact["contents"][0]["text"] == "# React"
    assert prompts_compact["prompts"][0]["name"] == "summarize-docs"
    assert get_prompt_compact["messages"][0]["content"] == "Summarize react"
