"""The governed default tool sets as admin-editable, versioned data (W22b)."""

from __future__ import annotations

import re
from typing import Any

from ..governed_default_tool_sets import GOVERNED_DEFAULT_TOOL_SETS, GovernedToolSet, ToolFamily
from .errors import (
    EMPTY_LIST,
    INVALID_ENTRY,
    INVALID_PAYLOAD,
    REQUIRED_TOOL_MISSING,
    UNKNOWN_TOOL,
    PolicyListError,
    refuse_duplicates,
)
from .records import PolicyListSpec, PolicyListState

REQUIRED_DEFAULT_SET_TOOLS = ("select_workflow",)
_FAMILY_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:\-]{0,127}$")


def _families_payload(tool_set: GovernedToolSet) -> list[dict[str, Any]]:
    return [{"name": family.name, "tools": list(family.tools)} for family in tool_set.families]


def _read_families(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("families")
    families: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("family")
        tools = item.get("tools")
        if not isinstance(tools, list) or not tools or not all(isinstance(tool, str) for tool in tools):
            raise ValueError("tools")
        families.append({"name": item["name"], "tools": list(tools)})
    return families


def _spec(tool_set: GovernedToolSet) -> PolicyListSpec:
    return PolicyListSpec(
        list_id=f"default_tool_set.{tool_set.capability_type}",
        config_key=f"policy.default_tool_set.{tool_set.capability_type}",
        key_prefix=tool_set.set_id,
        title=tool_set.title,
        description=tool_set.description,
        seed_values=lambda: _families_payload(tool_set),
        read_values=_read_families,
        seed_version=tool_set.version,
    )


DEFAULT_TOOL_SET_SPECS: dict[str, PolicyListSpec] = {
    capability_type: _spec(tool_set) for capability_type, tool_set in GOVERNED_DEFAULT_TOOL_SETS.items()
}


def tool_set_from_state(capability_type: str, state: PolicyListState) -> GovernedToolSet:
    seed = GOVERNED_DEFAULT_TOOL_SETS[capability_type]
    families = tuple(ToolFamily(family["name"], tuple(family["tools"])) for family in state.values)
    return GovernedToolSet(
        capability_type=seed.capability_type,
        set_id=seed.set_id,
        version=state.version,
        title=seed.title,
        description=seed.description,
        families=families,
    )


def catalog_tool_names(capability_type: str) -> set[str]:
    from ...tools.registry import get_all_tools_with_plugins

    definitions = get_all_tools_with_plugins(agent_type=capability_type)
    return {str(definition["function"]["name"]) for definition in definitions}


def validate_tool_set_families(raw: Any, *, catalog: set[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise PolicyListError(INVALID_PAYLOAD, "families must be a list of {name, tools} objects.")
    if not raw:
        raise PolicyListError(EMPTY_LIST, "A default tool set needs at least one family.")
    families: list[dict[str, Any]] = []
    for item in raw:
        name = str(item.get("name") or "").strip()
        if not _FAMILY_NAME.fullmatch(name):
            raise PolicyListError(INVALID_ENTRY, "A family name must be a lower-case identifier.", [name])
        tools_raw = item.get("tools")
        if not isinstance(tools_raw, list) or not all(isinstance(tool, str) for tool in tools_raw):
            raise PolicyListError(INVALID_PAYLOAD, "A family's tools must be a list of tool names.", [name])
        tools = [tool.strip() for tool in tools_raw if tool.strip()]
        if not tools:
            raise PolicyListError(EMPTY_LIST, "Every family needs at least one tool.", [name])
        invalid = [tool for tool in tools if not _TOOL_NAME.fullmatch(tool)]
        if invalid:
            raise PolicyListError(INVALID_ENTRY, "Tool names must be registered tool identifiers.", invalid)
        families.append({"name": name, "tools": tools})
    refuse_duplicates((family["name"] for family in families), what="The set")
    all_tools = [tool for family in families for tool in family["tools"]]
    refuse_duplicates(all_tools, what="The set")
    unknown = [tool for tool in all_tools if tool not in catalog]
    if unknown:
        raise PolicyListError(UNKNOWN_TOOL, "The capability's catalog does not offer these tools.", unknown)
    missing = [tool for tool in REQUIRED_DEFAULT_SET_TOOLS if tool not in all_tools]
    if missing:
        raise PolicyListError(
            REQUIRED_TOOL_MISSING,
            "Every default set keeps select_workflow: it is the explicit route to any workflow's own tools.",
            missing,
        )
    return families


def describe_tool_set(capability_type: str, state: PolicyListState, catalog: set[str]) -> dict[str, Any]:
    tool_set = tool_set_from_state(capability_type, state)
    return {
        **state.describe(),
        "capability_type": capability_type,
        "set_id": tool_set.set_id,
        "tool_count": len(tool_set.tools),
        "families": state.values,
        "unregistered_tools": [tool for tool in tool_set.tools if tool not in catalog],
    }


__all__ = [
    "DEFAULT_TOOL_SET_SPECS",
    "REQUIRED_DEFAULT_SET_TOOLS",
    "catalog_tool_names",
    "describe_tool_set",
    "tool_set_from_state",
    "validate_tool_set_families",
]
