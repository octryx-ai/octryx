"""Tool definitions for mcp domain."""

from __future__ import annotations

import copy

MCP_DEFINITIONS: dict[str, dict] = {
    "list_mcp_servers": {
        "type": "function",
        "function": {
            "name": "list_mcp_servers",
            "description": (
                "List registered MCP servers and their connection status. "
                "Use this before exploring MCP capabilities."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "include_disconnected": {
                        "type": "boolean",
                        "description": "Include disconnected servers as well. Defaults to true.",
                    },
                },
            },
        },
    },
    "list_mcp_server_tools": {
        "type": "function",
        "function": {
            "name": "list_mcp_server_tools",
            "description": (
                "List tools exposed by one MCP server on demand without injecting every MCP schema into the prompt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server_name": {"type": "string", "description": "Registered MCP server name"},
                    "search": {
                        "type": "string",
                        "description": "Optional keyword filter for tool names or descriptions",
                    },
                    "include_schema": {
                        "type": "boolean",
                        "description": (
                            "Include full input schema for each tool. Defaults to false for token efficiency."
                        ),
                    },
                    "auto_connect": {
                        "type": "boolean",
                        "description": "Automatically connect the server if needed. Defaults to true.",
                    },
                },
                "required": ["server_name"],
            },
        },
    },
    "call_mcp_server_tool": {
        "type": "function",
        "function": {
            "name": "call_mcp_server_tool",
            "description": "Execute one tool on a registered MCP server by server and tool name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_name": {"type": "string", "description": "Registered MCP server name"},
                    "tool_name": {"type": "string", "description": "Tool name as listed by list_mcp_server_tools"},
                    "arguments": {
                        "type": "object",
                        "description": "Arguments object for the selected MCP tool",
                        "additionalProperties": True,
                    },
                    "auto_connect": {
                        "type": "boolean",
                        "description": "Automatically connect the server if needed. Defaults to true.",
                    },
                },
                "required": ["server_name", "tool_name"],
            },
        },
    },
    "list_mcp_server_resources": {
        "type": "function",
        "function": {
            "name": "list_mcp_server_resources",
            "description": (
                "List the MCP resources this workspace governs for one server, without loading their "
                "content. Answered from the Workspace resource catalog, so only resources an "
                "administrator mirrored and enabled appear, and no connection is opened."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server_name": {"type": "string", "description": "Registered MCP server name"},
                    "search": {
                        "type": "string",
                        "description": (
                            "Optional keyword filter for resource id, name, or description"
                        ),
                    },
                },
                "required": ["server_name"],
            },
        },
    },
    "read_mcp_server_resource": {
        "type": "function",
        "function": {
            "name": "read_mcp_server_resource",
            "description": (
                "Read one governed MCP resource from a registered server. Resources are addressed "
                "by the opaque resource_id that list_mcp_server_resources returns; resource URIs "
                "are not accepted and any other identity is denied before transport."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server_name": {"type": "string", "description": "Registered MCP server name"},
                    "resource_id": {
                        "type": "string",
                        "description": "Governed resource id as listed by list_mcp_server_resources",
                    },
                    "auto_connect": {
                        "type": "boolean",
                        "description": "Automatically connect the server if needed. Defaults to true.",
                    },
                },
                "required": ["server_name", "resource_id"],
            },
        },
    },
    "list_mcp_server_prompts": {
        "type": "function",
        "function": {
            "name": "list_mcp_server_prompts",
            "description": (
                "List the MCP prompt templates this workspace governs for one server, without "
                "rendering them. Answered from the Workspace prompt catalog, so only prompts an "
                "administrator mirrored and enabled appear, and no connection is opened."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server_name": {"type": "string", "description": "Registered MCP server name"},
                    "search": {
                        "type": "string",
                        "description": "Optional keyword filter for prompt names or descriptions",
                    },
                },
                "required": ["server_name"],
            },
        },
    },
    "get_mcp_server_prompt": {
        "type": "function",
        "function": {
            "name": "get_mcp_server_prompt",
            "description": (
                "Render one governed MCP prompt template on a registered server. The prompt must be "
                "one returned by list_mcp_server_prompts; any other name is denied before transport."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server_name": {"type": "string", "description": "Registered MCP server name"},
                    "prompt_name": {
                        "type": "string",
                        "description": "Prompt name as listed by list_mcp_server_prompts",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments object for the selected MCP prompt",
                        "additionalProperties": True,
                    },
                    "auto_connect": {
                        "type": "boolean",
                        "description": "Automatically connect the server if needed. Defaults to true.",
                    },
                },
                "required": ["server_name", "prompt_name"],
            },
        },
    },
}


def get_mcp_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(MCP_DEFINITIONS)
