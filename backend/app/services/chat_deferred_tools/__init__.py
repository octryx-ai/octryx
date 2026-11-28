"""A chat sends its core tools in full and every other offered tool by name."""

from __future__ import annotations

from .catalog import (
    CHAT_CORE_TOOLS,
    CHAT_OMITTED_PARAMS,
    DIRECT_TOOL_LIMIT,
    TOOL_SEARCH,
    compact_catalog,
    direct_tool_names,
    lean_chat_schema,
    split_chat_tools,
    tool_search_definition,
)
from .matching import (
    closest_tool_names,
    defer_chat_tools,
    select_tool_names,
    sent_chat_tool_definitions,
    session_loaded_tool_names,
)
from .prompt_sections import drop_unused_prompt_sections
from .search import chat_tool_search

__all__ = [
    "CHAT_CORE_TOOLS",
    "DIRECT_TOOL_LIMIT",
    "TOOL_SEARCH",
    "chat_tool_search",
    "closest_tool_names",
    "CHAT_OMITTED_PARAMS",
    "compact_catalog",
    "defer_chat_tools",
    "direct_tool_names",
    "drop_unused_prompt_sections",
    "lean_chat_schema",
    "select_tool_names",
    "sent_chat_tool_definitions",
    "session_loaded_tool_names",
    "split_chat_tools",
    "tool_search_definition",
]
