"""The tool catalog for tool-set editing, grouped by connector and risk.

It holds what either surface can offer: the registry's tools (the chat) and the Knowledge MCP server's tools (the
octryx client), so one tool set covers both using the same permission filter.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from .tool_sets import RISKS, entries_match, is_selector

SELECTORS = (
    {"entry": "risk:read", "label": "Every read tool"},
    {"entry": "risk:write", "label": "Every write tool"},
    {"entry": "risk:admin", "label": "Every administration tool"},
    {"entry": "connector:*:write", "label": "Every connector write"},
)
PLATFORM = "Platform"


@lru_cache(maxsize=1)
def _catalog() -> tuple[tuple[str, str, str, str], ...]:
    """(name, connector, risk, description) of every tool of both surfaces."""
    from ...tools.definitions import get_all_definitions, get_tool_definition_metadata
    from ...tools.definitions.connector_ownership import SERVICE_ONLY_TOOLS

    descriptions: dict[str, str] = {}
    for name, definition in get_all_definitions().items():
        if name in SERVICE_ONLY_TOOLS:
            continue
        function = definition.get("function") if isinstance(definition, dict) else None
        descriptions[name] = str((function or {}).get("description") or "")
    try:
        from ..mcp_knowledge_protocol import build_knowledge_mcp_server

        for name, description in build_knowledge_mcp_server().code_tool_descriptions().items():
            descriptions.setdefault(name, description)
    except Exception:  # noqa: BLE001 — the catalog lists the registry even when the MCP server cannot be built
        pass
    rows = []
    for name in sorted(descriptions):
        metadata = get_tool_definition_metadata(name)
        connector = str(metadata.connector or "") if metadata.owner_type == "connector" else ""
        risk = str(metadata.risk or "")
        rows.append((name, connector, risk if risk in RISKS else "write", descriptions[name].split("\n")[0][:300]))
    return tuple(rows)


def catalog_tool_names() -> list[str]:
    return [row[0] for row in _catalog()]


def tool_catalog(entries: list[str] | None = None) -> dict[str, Any]:
    """The grouped catalog; ``in_set`` against ``entries`` (one function's tool set) when given."""
    chosen = list(entries or [])
    groups: dict[str, dict[str, Any]] = {}
    for name, connector, risk, description in _catalog():
        group = groups.setdefault(connector, {"connector": connector or None,
                                              "label": connector.replace("_", " ").title() if connector else PLATFORM,
                                              "risks": {key: [] for key in RISKS}})
        group["risks"][risk].append({"name": name, "description": description,
                                     "in_set": entries_match(chosen, name) if chosen else False})
    names = {row[0] for row in _catalog()}
    unknown = [entry for entry in chosen if not is_selector(entry) and entry not in names]
    ordered = sorted(groups.values(), key=lambda item: (item["connector"] is not None, item["label"]))
    return {"groups": ordered, "selectors": list(SELECTORS), "unknown_entries": unknown}


__all__ = ["SELECTORS", "catalog_tool_names", "tool_catalog"]
