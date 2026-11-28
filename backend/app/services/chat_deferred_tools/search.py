"""``tool_search`` in a chat turn."""

from __future__ import annotations

import re
from typing import Any

from .catalog import CHAT_CORE_TOOLS
from .matching import _select_names, select_tool_names


def _query_key(query: str) -> str:
    return " ".join(str(query or "").lower().split())


def _unmatched_note(query: str, catalog: dict[str, dict], core: set[str]) -> str:
    wanted = _select_names(query) or []
    callable_now = [name for name in wanted if name in core]
    missing = [name for name in wanted if name not in catalog and name not in core]
    parts = []
    if callable_now:
        parts.append(f"Already callable, no search needed: {', '.join(callable_now)}.")
    if missing:
        parts.append(f"Not offered under that name: {', '.join(missing)}.")
    return " ".join(parts)


async def chat_tool_search(params: dict[str, Any], context: Any) -> dict[str, Any]:
    """``tool_search`` in a chat turn: load the named (or closest) deferred tools for the next model call and
    session."""
    query = str(params.get("query") or "")
    catalog = context.deferred_tool_catalog or {}
    direct = set(getattr(context, "chat_direct_tool_names", None) or ())
    core = set(CHAT_CORE_TOOLS) | direct
    selected = select_tool_names(query, catalog, core, direct)
    names = [name for name in selected if name in catalog]
    callable_close = [name for name in selected if name not in catalog]
    asked = getattr(context, "tool_search_queries", None)
    if asked is None:
        asked = {}
        context.tool_search_queries = asked
    key = _query_key(query)
    if key in asked:
        earlier = asked[key]
        return {"loaded": [], "note": ("You already asked this in this turn. " + (
            f"The closest offered tools are {', '.join(earlier)}; they are already callable. Use one of them, or "
            "tell the person what is not available and stop." if earlier else
            "Nothing offered is close: tell the person it is not available here and stop."))}
    asked[key] = [*names, *callable_close]
    unmatched = _unmatched_note(query, catalog, core)
    if callable_close:
        unmatched = (f"{unmatched} Already callable and close: {', '.join(callable_close)}.").strip()
    wanted = _select_names(query) or []
    if not names and ((wanted and set(wanted) <= core) or callable_close):
        # ``select:create_jira_ticket`` for a tool sent in full: callable now, never "not available, stop".
        return {"loaded": [], "note": unmatched + " Call it directly."}
    if not names:
        return {"loaded": [], "note": ((unmatched + " ") if unmatched else "") + (
            "No offered tool is close. If the person asked for it, tell them it is not available here and stop; do not "
            "use a different tool instead.")}
    context.discovered_tool_names.update(names)
    # No schemas in the result: the loaded tools are sent in full with the next request
    # anyway; a copy in the tool result rode along in the history of every later model call (~1.8k characters each).
    note = "These tools are callable from your next step on; their schemas come with the tools."
    if unmatched:
        note = (f"{unmatched} The closest offered tools are loaded instead: {', '.join(names)}. Use one if it does "
                "what you need; otherwise tell the person it is not available and stop.")
    if _select_names(query) is None:
        note += (" If none of them does what the person asked, say it is not available and stop; do not use a "
                 "different tool instead.")
    return {"loaded": names, "tools": [_tool_line(catalog[name]) for name in names], "note": note}


def _tool_line(definition: dict[str, Any]) -> dict[str, str]:
    function = definition.get("function") or {}
    description = " ".join(str(function.get("description") or "").split())
    first = re.split(r"(?<=[.!?])\s", description, maxsplit=1)[0]
    return {"name": str(function.get("name") or ""), "does": first[:160]}
