"""Which deferred tools a ``tool_search`` query loads, and which a chat turn and its session have loaded."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from .catalog import (
    _KEYWORD_RESULTS,
    CHAT_CORE_TOOLS,
    SELECT_PREFIX,
    TOOL_SEARCH,
    _name,
    compact_catalog,
    direct_tool_names,
    lean_chat_schema,
    split_chat_tools,
    tool_search_definition,
)

_CLOSEST_RESULTS = 3
# Verbs say what a tool does, not what it is about: a guessed ``get_jira_transitions`` must find
# ``list_jira_transitions``, so the read verbs count as one and no verb alone makes a tool "close".
_READ_VERBS = {"get", "list", "read", "fetch", "show", "find", "search", "describe", "view", "lookup"}
_VERBS = _READ_VERBS | {"create", "update", "delete", "add", "set", "post", "remove", "write", "edit", "start"}
# Words that say nothing about a tool's subject (``select:no_such_tool`` must stay "not available").
_FILLER = {"tool", "no", "such", "the", "a", "an", "of", "for", "to", "and", "in", "on", "by", "with", "my", "all"}


def _tokens(text: str) -> set[str]:
    """Lower-case word tokens with a plural ``s`` dropped and the read verbs folded into ``read``."""
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", str(text or "").lower()):
        token = token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token
        tokens.add("read" if token in _READ_VERBS else token)
    return tokens


def _closeness(terms: set[str], name: str, definition: dict, *, by_name: bool = False) -> int:
    """How close a tool is to the query terms: subject words in the name count most, then the description.

    0 means not close: a tool shares no subject word (only a verb, or nothing) with the query. For a guessed tool name
    (``by_name``) a subject word must be in the tool's name: a description mention is too loose for a name.
    """
    nouns = {term for term in terms if term not in _VERBS and term not in _FILLER and term != "read"}
    name_terms = _tokens(name)
    description = _tokens((definition.get("function") or {}).get("description") or "")
    name_nouns = len(nouns & name_terms)
    description_nouns = len(nouns & description)
    if not name_nouns and (by_name or description_nouns < 2):
        return 0
    return 4 * name_nouns + description_nouns + len((terms - nouns) & name_terms)


def closest_tool_names(query: str, catalog: dict[str, dict], *, limit: int = _CLOSEST_RESULTS,
                       by_name: bool = False) -> list[str]:
    """The offered tools closest to a query or guessed tool name, best first; empty when nothing is close."""
    terms = _tokens(query)
    asks_write = bool(terms & (_VERBS - _READ_VERBS))
    # Close reads come before close writes unless the query asks for a write (with the listing reduced to families,
    # "confluence page" must reach get_confluence_page and search_confluence before the writes).
    scored = [(not asks_write and _is_write_name(name), -score, name) for name, definition in catalog.items()
              if (score := _closeness(terms, name, definition, by_name=by_name))]
    return [name for _write, _score, name in sorted(scored)[:limit]]


def _is_write_name(name: str) -> bool:
    return name.split("_", 1)[0] in _VERBS - _READ_VERBS


def _select_names(query: str) -> list[str] | None:
    text = str(query or "").strip()
    if not text.lower().startswith(SELECT_PREFIX):
        return None
    return list(dict.fromkeys(part.strip() for part in text[len(SELECT_PREFIX):].split(",") if part.strip()))


def select_tool_names(query: str, catalog: dict[str, dict], core: Iterable[str] = CHAT_CORE_TOOLS,
                      direct: Iterable[str] = ()) -> list[str]:
    """The deferred tools a ``tool_search`` query loads: ``select:`` names, else the best keyword matches.

    A ``select:`` name that is not offered loads its closest offered tools instead. Otherwise a weak
    model's ``select:get_jira_transitions`` gets "no offered tool matches, stop" while ``list_jira_transitions``
    exists, and the model retries until the tool-call limit. A weak model guesses names; the closest real ones end
    the guessing.
    """
    wanted = _select_names(query)
    if wanted is None:
        return closest_tool_names(query, catalog, limit=_KEYWORD_RESULTS)
    names: list[str] = []
    for name in wanted:
        if name in catalog:
            names.append(name)
        elif name not in set(core):
            # A guessed name's closest tools, also among those already sent in full (``direct``): those are named
            # as callable, never loaded again.
            candidates = {**{tool: {} for tool in direct}, **catalog}
            names.extend(closest_tool_names(name.replace("_", " "), candidates, by_name=True))
    return list(dict.fromkeys(names))


def sent_chat_tool_definitions(tool_definitions: list[dict[str, Any]], catalog: dict[str, dict],
                               loaded: Iterable[str] | None) -> list[dict[str, Any]]:
    """The definitions a chat request sends: everything not deferred, plus the deferred tools already loaded."""
    keep = set(loaded or ())
    return [definition for definition in tool_definitions
            if _name(definition) not in catalog or _name(definition) in keep]


def session_loaded_tool_names(history: Iterable[Any], catalog: dict[str, dict]) -> set[str]:
    """The deferred tools this session loaded or called in earlier turns, read from its stored messages."""
    loaded: set[str] = set()
    for message in history:
        for call in getattr(message, "tool_calls", None) or ():
            function = call.get("function") if isinstance(call, dict) else None
            name = str((function or {}).get("name") or "").strip()
            if name == TOOL_SEARCH:
                try:
                    arguments = json.loads((function or {}).get("arguments") or "{}")
                except (TypeError, ValueError):
                    arguments = {}
                loaded.update(select_tool_names(str((arguments or {}).get("query") or ""), catalog))
            elif name in catalog:
                loaded.add(name)
    return loaded


def defer_chat_tools(tool_definitions: list[dict[str, Any]], *, families: Iterable[Any], history: Iterable[Any],
                     context: Any) -> list[dict[str, Any]]:
    """Set up a chat turn's deferral on ``context``; returns the offered definitions with this turn's tool_search."""
    if not any(_name(definition) == TOOL_SEARCH for definition in tool_definitions):
        return tool_definitions
    tool_definitions = [lean_chat_schema(definition) for definition in tool_definitions]
    direct = direct_tool_names(tool_definitions)
    _core, catalog = split_chat_tools(tool_definitions, direct)
    context.chat_direct_tool_names = set(direct)
    if not catalog:
        # Everything is sent in full: tool_search would only cost its schema.
        return [definition for definition in tool_definitions if _name(definition) != TOOL_SEARCH]
    context.deferred_tool_catalog = catalog
    context.discovered_tool_names.update(session_loaded_tool_names(history, catalog))
    search = tool_search_definition(compact_catalog(catalog, families))
    return [search if _name(definition) == TOOL_SEARCH else definition for definition in tool_definitions]
