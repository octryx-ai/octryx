"""The chat's core tools, the deferred catalog, and the ``tool_search`` definition that lists it by family."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

TOOL_SEARCH = "tool_search"
SELECT_PREFIX = "select:"
_KEYWORD_RESULTS = 5
# Sent in full on every chat request: what most chat turns use first. Everything else is one tool_search away.
CHAT_CORE_TOOLS: tuple[str, ...] = (
    TOOL_SEARCH,
    "select_workflow",
    # start_workflow is deferred: it needs list_available_workflows, itself one tool_search away, so
    # the one search loads both; no eval or live chat called it.
    "ask_clarification",
    # A chat's writes run under one plan the person confirms once (chat_write_plan): always in full, never deferred.
    "propose_write_plan",
    "knowledge_search",
    "knowledge_read",
    "memory_recall",
    "web_search",
    "search_jira_tickets",
    "get_jira_ticket",
    # The two writes a chat asks for most: deferred, every write turn spends one model
    # call on ``tool_search("select:create_jira_ticket")`` first. Sent in full only when the turn offers them (the
    # connection decides); the confirmed write plan still governs every call.
    "create_jira_ticket",
    "add_jira_comment",
)
# Optional parameters a chat request leaves out of the schemas it sends in full: the
# core schemas ride on every model call of a chat turn, about four per task. None of these was used in any eval or
# live chat; the tool still accepts them, and a workflow phase or the MCP clients keep the full schema.
CHAT_OMITTED_PARAMS: dict[str, tuple[str, ...]] = {
    "web_search": ("exclude_domains", "exclude_terms", "exclude_preprints"),
    "search_jira_tickets": ("fix_version", "start_at"),  # fix_versions takes one name as well
    "ask_clarification": ("priority", "context_snapshot"),
    "memory_recall": ("classes",),
    "propose_write_plan": ("scope",),  # the written fields' projects, issues and branches are its scope already
}
CONNECTOR_WRITES_GROUP = "connector_writes"
# A turn that offers at most this many tools gets them all in full and no tool_search (nothing left to defer).
DIRECT_TOOL_LIMIT = 25


def _name(definition: dict[str, Any]) -> str:
    return str((definition.get("function") or {}).get("name") or "").strip()


def split_chat_tools(tool_definitions: list[dict[str, Any]],
                     direct: Iterable[str] = ()) -> tuple[list[dict[str, Any]], dict[str, dict]]:
    """The core definitions and the deferred catalog (name -> full definition) of a chat turn's offered tools."""
    sent = set(CHAT_CORE_TOOLS) | set(direct)
    core = [definition for definition in tool_definitions if _name(definition) in sent]
    deferred = {_name(definition): definition for definition in tool_definitions
                if _name(definition) and _name(definition) not in sent}
    return core, deferred


def lean_chat_schema(definition: dict[str, Any]) -> dict[str, Any]:
    """``definition`` without the optional parameters a chat leaves out (``CHAT_OMITTED_PARAMS``); a copy if changed."""
    omitted = set(CHAT_OMITTED_PARAMS.get(_name(definition), ()))
    parameters = (definition.get("function") or {}).get("parameters")
    properties = (parameters or {}).get("properties") if isinstance(parameters, dict) else None
    if not omitted or not isinstance(properties, dict) or not omitted & set(properties):
        return definition
    required = set(parameters.get("required") or ())
    kept = {name: schema for name, schema in properties.items() if name not in omitted or name in required}
    return {**definition, "function": {**definition["function"], "parameters": {**parameters, "properties": kept}}}


def direct_tool_names(tool_definitions: list[dict[str, Any]]) -> list[str]:
    """The offered tools sent in full besides the core: all of them when the turn offers at most 25, else none.

    Deferral pays only for a large catalog. Sending the connected integrations' reads in full as well (Confluence,
    Bitbucket, Jira extras: +9 schemas) saves a tool_search call but costs ~4k input tokens on every model call
    (about +11 % input tokens over a chat eval, same score). So a large catalog keeps its connected reads behind
    tool_search.
    """
    offered = [name for definition in tool_definitions if (name := _name(definition))]
    if len(offered) - (TOOL_SEARCH in offered) > DIRECT_TOOL_LIMIT:
        return []
    return [name for name in offered if name != TOOL_SEARCH and name not in CHAT_CORE_TOOLS]


# One line per family instead of every tool name (the full name list is ~2.8k characters on every chat model call;
# this stays at most 1k). A search result names the tools and what they do.
_FAMILY_HINTS: dict[str, str] = {
    "workflow_selection": "list_available_workflows, start_workflow",
    "turn_context": "time, instructions, older tool results",
    "knowledge": "Knowledge changes, code impact, remember",
    "skills": "operating methods",
    "web": "fetch a URL",
    "mcp_bridge": "MCP servers",
    "shell": "read-only CLI",
    "delegation": "sub-agents",
    "work_items": "work items",
    "work_lifecycle": "find, plan, hand over work items",
    "coordination": "team board, claims",
    "run_steering": "workflow and product runs, approvals, tasks",
    "knowledge_extras": "Knowledge sources, entities",
    "knowledge_graph": "graph, release status",
    "diagrams": "diagrams",
}
# Connector families are summed up by the systems their offered tools reach, so the line stays filtered.
_SYSTEMS: tuple[tuple[str, str], ...] = (
    ("jira", "Jira"), ("confluence", "Confluence"), ("bitbucket", "Bitbucket"), ("github", "GitHub"),
    ("gitlab", "GitLab"), ("k8s", "Kubernetes"), ("pod", "Kubernetes"), ("aws", "AWS"), ("servicenow", "ServiceNow"),
)


def _systems(names: Iterable[str]) -> str:
    found = [label for token, label in _SYSTEMS for name in names if token in name.split("_") or
             token in name.replace("_", " ").split()]
    return ", ".join(dict.fromkeys(found))


def _family_line(family: str, names: list[str]) -> str:
    hint = _FAMILY_HINTS.get(family)
    if hint is None:
        systems = _systems(names)
        hint = systems if systems else ", ".join(names[:3]) + (", ..." if len(names) > 3 else "")
    return f"- {family}: {hint}"


def compact_catalog(deferred_names: Iterable[str], families: Iterable[Any]) -> str:
    """One line per family of deferred tools (connector writes in their own line); names come with a search."""
    from ..run_capability.chat_writes import is_chat_connector_write_tool

    remaining = list(dict.fromkeys(deferred_names))
    writes = [name for name in remaining if is_chat_connector_write_tool(name)]
    lines: list[str] = []
    grouped: set[str] = set(writes)
    for family in families:
        names = [name for name in family.tools if name in remaining and name not in grouped]
        if names:
            lines.append(_family_line(family.name, names))
            grouped.update(names)
    other = [name for name in remaining if name not in grouped]
    if other:
        lines.append(_family_line("other", other))
    if writes:
        lines.append(f"- {CONNECTOR_WRITES_GROUP}: {_systems(writes)} (confirmed write plan only)")
    return "\n".join(lines)


def tool_search_definition(catalog: str) -> dict[str, Any]:
    """``tool_search`` for this chat turn: its description names the deferred tool families in one line each."""
    return {
        "type": "function",
        "function": {
            "name": TOOL_SEARCH,
            "description": (
                "More tools, by family. Search with keywords (e.g. 'confluence page', 'pull requests') to load the "
                "closest ones, or select:<name>,<name> for names you know; they are callable from your next step on. "
                "If nothing found does what the person asked, say it is not available and stop.\n" + catalog
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string",
                                         "description": "keywords, or select:<name>[,<name>...] for exact names"}},
                "required": ["query"],
            },
        },
    }
