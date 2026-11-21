"""Tool implementations for lazy tool discovery."""

from __future__ import annotations

from typing import Any

from .context import ToolContext
from .discovery_impl import execute_tool_schema_get, execute_tool_search


class ToolSearchTool:
    name = "tool_search"
    description = "Search discoverable long-tail tools by keyword. Returns compact metadata only."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if getattr(context, "deferred_tool_catalog", None) is not None:
            # A chat turn: load deferred tools' schemas for the next model call (``services/chat_deferred_tools``).
            from ..services.chat_deferred_tools import chat_tool_search

            return await chat_tool_search(params, context)
        return await execute_tool_search(params, context)


class ToolSchemaGetTool:
    name = "tool_schema_get"
    description = "Load the full callable schema for a single long-tail tool by name."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await execute_tool_schema_get(params, context)
