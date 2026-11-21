"""Approach A: lazy tool-discovery surface (Claude-Code-style ToolSearch).

Instead of routing/keyword-picking a per-message tool allowlist, expose a small
always-on CORE surface plus the discovery tools (``tool_search`` /
``tool_schema_get``); the ~450 long-tail tools are reached on demand — the model
searches, loads a schema (which activates the tool for this run), then calls it.

This is the explicit alternative to the keyword context-routing tool allowlist.
It is opt-in per project/runtime (``tool_surface_mode == "discovery"``) so it can
be benchmarked against the routing path without changing the default.
"""

from __future__ import annotations

from typing import Any

from ....tools.definitions import (
    get_all_definitions,
    get_tool_definition_metadata,
    is_tool_definition_available_for_agent_type,
)
from ....tools.visibility import tool_visibility_decision

_DISCOVERY_TOOL_NAMES = ("tool_search", "tool_schema_get")


def is_discovery_mode(project_config: Any, runtime_settings: Any) -> bool:
    for source in (project_config, runtime_settings):
        if isinstance(source, dict) and str(source.get("tool_surface_mode") or "").strip().lower() == "discovery":
            return True
    return False


def discovery_tool_surface(
    *,
    capability_type: str | None,
    discovered_tool_names: set[str] | None,
    project_config: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Core + discovery tools + already-activated long-tail tools.

    Returns (definitions, allowed_names). Long-tail tools appear only after the
    model activated them via tool_schema_get (recorded on the ToolContext).
    """
    agent_type = str(capability_type or "diagnosis")
    activated = {str(name).strip() for name in (discovered_tool_names or set()) if str(name).strip()}
    definitions: list[dict[str, Any]] = []
    names: set[str] = set()
    for tool_name, definition in get_all_definitions().items():
        metadata = get_tool_definition_metadata(tool_name)
        keep = metadata.is_core or tool_name in _DISCOVERY_TOOL_NAMES or tool_name in activated
        if not keep:
            continue
        if not is_tool_definition_available_for_agent_type(tool_name, agent_type):
            continue
        try:
            if not tool_visibility_decision(tool_name, project_config).visible:
                continue
        except Exception:  # noqa: BLE001 - visibility is best-effort here
            pass
        definitions.append(definition)
        names.add(tool_name)
    return definitions, names
