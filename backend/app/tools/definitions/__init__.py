"""Assembled tool definitions from all domain modules."""

from __future__ import annotations

from dataclasses import dataclass

from .classification import (
    ADMIN_DEFINITION_NAMES,
    CHANGE_ONLY_DEFINITION_NAMES,
    CONNECTOR_PROVIDER_BY_TOOL,
    CORE_DEFINITION_NAMES,
    DATABASE_DEFINITION_NAMES,
    EXECUTION_DEFINITION_NAMES,
    GIT_DEFINITION_NAMES,
    KNOWN_DEFINITION_NAMES,
    MCP_DEFINITION_NAMES,
    MUTATING_DEFINITION_NAMES,
    PLAN_EXCLUDED_DEFINITION_NAMES,
    PLAN_ONLY_DEFINITION_NAMES,
    WORKSPACE_DEFINITION_NAMES,
)
from .getters import DEFINITION_GETTERS
from .rest_tool_classes import rest_write_class


@dataclass(frozen=True)
class ToolDefinitionMetadata:
    """Canonical discovery/filtering metadata attached to a tool definition."""

    change_only: bool = False
    plan_excluded: bool = False
    plan_only: bool = False
    is_core: bool = True
    owner_type: str = "built_in"
    source: str = "base"
    risk: str = "read"
    approval_required: bool = False
    connector: str | None = None
    required_config: str | None = None
    scopes: tuple[str, ...] = ()
    mutates_state: bool = False
    filesystem_access: str = "none"
    network_access: str = "none"
    audit_required: bool = False


_DYNAMIC_PLUGIN_TOOL_METADATA: dict[str, ToolDefinitionMetadata] = {}


def register_plugin_tool_metadata(tool_name: str, metadata: ToolDefinitionMetadata) -> None:
    normalized_name = str(tool_name or "").strip()
    if normalized_name:
        _DYNAMIC_PLUGIN_TOOL_METADATA[normalized_name] = metadata


def clear_plugin_tool_metadata() -> None:
    _DYNAMIC_PLUGIN_TOOL_METADATA.clear()


def get_all_definitions() -> dict[str, dict]:
    """Merge all domain definitions into one dict; connector tools get their routing parameters."""
    from ...services.named_connections.tool_params import with_connection_params

    result: dict[str, dict] = {}
    for getter in DEFINITION_GETTERS:
        definitions = getter()
        for name, definition in definitions.items():
            if name in result:
                raise ValueError(f"Duplicate tool definition: {name}")
            result[name] = definition
    return with_connection_params(result)


# (source, owner_type, required_config, scopes, network_access) of a tool, by where its definition comes from.
_Origin = tuple[str, str, str | None, tuple[str, ...], str]


def _definition_origin(normalized_name: str, connector: str | None) -> _Origin:
    if connector:
        return "connector", "connector", f"connector:{connector}", (f"connector:{connector}",), "connector"
    if normalized_name in DATABASE_DEFINITION_NAMES:
        return "database", "built_in", None, ("cloud-database:read",), "database"
    if normalized_name.startswith("database_tool_"):
        return "database", "dynamic_database", "database_tool_registry", ("database:query_tool",), "database"
    if normalized_name.startswith("rest__"):
        # Custom REST connector: an operation is a database row, so whether it writes is the connector's in-process
        # view of it (``rest_tool_classes``), refreshed before every dispatch; a write is risk ``write`` below.
        scopes = ("rest_api:write",) if rest_write_class(normalized_name) else ("rest_api:read",)
        return "rest", "dynamic_rest", "rest_api_registry", scopes, "connector"
    if normalized_name in MCP_DEFINITION_NAMES or normalized_name.startswith("mcp__"):
        return "mcp", "mcp", "mcp_server", ("mcp:server",), "mcp"
    if normalized_name.startswith("run_flow_"):
        return "workflow", "runtime_bridge", "published_flow_capability", ("workflow:execute",), "none"
    if normalized_name not in KNOWN_DEFINITION_NAMES:
        return "unknown", "unknown", "tool_definition_metadata", (), "unknown"
    return "base", "built_in", None, (), "none"


def _definition_risk(normalized_name: str, owner_type: str) -> str:
    if owner_type == "unknown":
        return "unknown"
    if normalized_name in ADMIN_DEFINITION_NAMES:
        return "admin"
    if normalized_name in MUTATING_DEFINITION_NAMES:
        return "write"
    if owner_type == "dynamic_rest" and rest_write_class(normalized_name):
        return "write"
    return "read"


def _filesystem_access(normalized_name: str, mutates_state: bool) -> str:
    if normalized_name in WORKSPACE_DEFINITION_NAMES or normalized_name in GIT_DEFINITION_NAMES:
        return "write" if mutates_state else "read"
    if normalized_name in EXECUTION_DEFINITION_NAMES:
        return "workspace"
    return "none"


def get_tool_definition_metadata(tool_name: str) -> ToolDefinitionMetadata:
    """Return canonical discovery/filtering metadata for a tool definition."""

    normalized_name = str(tool_name or "").strip()
    if not normalized_name:
        return ToolDefinitionMetadata()
    dynamic_plugin_metadata = _DYNAMIC_PLUGIN_TOOL_METADATA.get(normalized_name)
    if dynamic_plugin_metadata is not None:
        return dynamic_plugin_metadata
    connector = CONNECTOR_PROVIDER_BY_TOOL.get(normalized_name)
    source, owner_type, required_config, scopes, network_access = _definition_origin(normalized_name, connector)
    risk = _definition_risk(normalized_name, owner_type)
    mutates_state = risk in {"write", "admin"}
    audit_required = risk in {"write", "admin", "unknown"} or source in {"connector", "database", "mcp", "rest", "unknown"}
    return ToolDefinitionMetadata(
        change_only=normalized_name in CHANGE_ONLY_DEFINITION_NAMES,
        plan_excluded=normalized_name in PLAN_EXCLUDED_DEFINITION_NAMES,
        plan_only=normalized_name in PLAN_ONLY_DEFINITION_NAMES,
        is_core=normalized_name in CORE_DEFINITION_NAMES,
        owner_type=owner_type,
        source=source,
        risk=risk,
        approval_required=risk in {"write", "admin", "unknown"},
        connector=connector,
        required_config=required_config,
        scopes=scopes,
        mutates_state=mutates_state,
        filesystem_access=_filesystem_access(normalized_name, mutates_state),
        network_access=network_access,
        audit_required=audit_required,
    )


def is_tool_definition_available_for_agent_type(tool_name: str, agent_type: str) -> bool:
    """Return whether a tool definition should be exposed for an agent type."""

    metadata = get_tool_definition_metadata(tool_name)

    if metadata.plan_only:
        return agent_type == "plan"

    if agent_type == "diagnosis":
        return not metadata.change_only

    if agent_type == "plan":
        return not metadata.plan_excluded

    return True


def get_core_tool_names(agent_type: str = "diagnosis") -> list[str]:
    """Return names of core tools for an agent type (always directly available)."""
    return [
        name
        for name in get_all_definitions()
        if is_tool_definition_available_for_agent_type(name, agent_type) and get_tool_definition_metadata(name).is_core
    ]


def get_discoverable_tool_names(agent_type: str = "diagnosis") -> list[str]:
    """Return names of discoverable (long-tail) tools for an agent type."""
    return [
        name
        for name in get_all_definitions()
        if is_tool_definition_available_for_agent_type(name, agent_type)
        and not get_tool_definition_metadata(name).is_core
    ]
