"""A chat that offers few tools sends them all, without tool_search; a large catalog keeps deferral (sending the
connected reads in full costs about 11 % more input tokens)."""

from __future__ import annotations

from app.services.chat_deferred_tools import (
    CHAT_CORE_TOOLS,
    DIRECT_TOOL_LIMIT,
    defer_chat_tools,
    direct_tool_names,
)
from app.tools.context import ToolContext


def _names(definitions) -> set[str]:
    return {definition["function"]["name"] for definition in definitions}


def test_a_small_offered_set_is_sent_whole_without_tool_search():
    def tool(name):
        return {"type": "function", "function": {"name": name, "description": name, "parameters": {}}}

    small = [tool(name) for name in ("tool_search", "knowledge_search", "work_item_list", "workflow_run_status")]
    context = ToolContext(user_id="u", project_ids=[], roles=["member"], session_id="s", project_config={})

    sent = defer_chat_tools(small, families=(), history=[], context=context)

    assert _names(sent) == {"knowledge_search", "work_item_list", "workflow_run_status"}
    assert context.deferred_tool_catalog is None
    large = [tool(name) for name in CHAT_CORE_TOOLS] + [tool(f"extra_{n}") for n in range(DIRECT_TOOL_LIMIT)]
    assert direct_tool_names(large) == [], "a large catalog keeps tool_search"
