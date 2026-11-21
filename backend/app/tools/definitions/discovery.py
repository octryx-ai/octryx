"""Tool definitions for the lazy tool discovery runtime."""

from __future__ import annotations


def get_discovery_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for discovery tools."""
    return {
        "tool_search": {
            "type": "function",
            "function": {
                "name": "tool_search",
                "description": "Search available long-tail tools by keyword. Returns compact metadata only (no schema). "
                "Use this to discover tools for uncommon tasks before calling tool_schema_get to load their schema.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to filter tools by keyword, purpose, or domain.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return.",
                            "default": 10,
                        },
                        "source": {
                            "type": "string",
                            "description": "Filter by tool source: base, connector, mcp, plugin, database.",
                        },
                        "risk": {
                            "type": "string",
                            "description": "Filter by risk level: read, write, admin, unknown.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        "tool_schema_get": {
            "type": "function",
            "function": {
                "name": "tool_schema_get",
                "description": "Load the full callable schema for a single long-tail tool by name. "
                "Call tool_search first to find the exact tool name. Only returns schema when policy allows it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "The exact name of the tool to load.",
                        },
                    },
                    "required": ["tool_name"],
                },
            },
        },
    }
