"""A chat sends its core tools in full and every other offered tool by name.

Sending ~52k characters of tool schemas per chat request is too much, so the chat does what the Octryx client does. An
interactive client session defers its MCP tools: the model sees their names, ``ToolSearch`` loads the schemas it needs,
and those tools are callable from then on. The chat does the same:

- **core** (``CHAT_CORE_TOOLS``, about ten): sent with full schemas on every request;
- **deferred**: every other tool the turn offers. It is already filtered by catalog, connections and Workspace policy
  (``run_context_tooling``). The tool_search description lists the deferred tools by name, grouped by the governed
  set's families;
- ``tool_search`` (``select:<a,b>`` or keywords) returns the matching deferred tools' full schemas. They are sent from
  the next model call of the turn on, and for the rest of the session: a later turn re-derives what the session loaded
  from its stored messages (``session_loaded_tool_names``), so nothing depends on a session-metadata write that a turn
  could overwrite.

A workflow run's phase turn keeps its phase-only surface (``run_context`` defers only chat turns of a governed default
or Workspace-policy surface).
"""

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
