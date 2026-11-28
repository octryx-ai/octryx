"""Tool registry – maps tool names to implementations."""

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from app.tools.registry_impl._registry_toolset_connectors import TOOL_CLASSES_CONNECTORS
from app.tools.registry_impl._registry_toolset_ops_trackers import TOOL_CLASSES_OPS_TRACKERS
from app.tools.registry_impl._registry_toolset_workflow import TOOL_CLASSES_WORKFLOW
from app.tools.registry_impl._registry_toolset_workspace import TOOL_CLASSES_WORKSPACE

from ..services.ai_marking_tools import marked_arguments
from ..services.named_connections.tool_routing import routed_execute
from .connectors.web_url_sources import link_configured_web_sources
from .context import ToolContext
from .definitions import get_all_definitions, get_tool_definition_metadata, is_tool_definition_available_for_agent_type
from .definitions.connector_ownership import SERVICE_ONLY_TOOLS
from .registry_dispatch import (
    _breaker_gate,
    _execute_database_tool,
    _execute_mcp_tool,
    _execute_plugin_tool,
    _execute_rest_tool,
    _record_breaker,
)
from .registry_governance import _run_governed_tool_checks
from .registry_impl._registry_toolset_aux import TOOL_CLASSES_AUX
from .result_content import content_checked
from .results import annotate_tool_result_payload, safe_tool_error_message


@dataclass(frozen=True)
class ToolRegistryEntry:
    name: str
    owner_type: str
    source: str
    connector: str | None
    risk: str
    required_config: str | None
    mutates_state: bool
    approval_required: bool
    implementation_module: str
    implementation_class: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Registry: tool_name -> tool instance
TOOL_REGISTRY: dict[str, Any] = {}
TOOL_REGISTRY_ENTRIES: dict[str, ToolRegistryEntry] = {}


def _registry_entry_for_tool(tool_instance: Any) -> ToolRegistryEntry:
    tool_name = str(tool_instance.name)
    metadata = get_tool_definition_metadata(tool_name)
    tool_class = tool_instance.__class__
    return ToolRegistryEntry(
        name=tool_name,
        owner_type=metadata.owner_type,
        source=metadata.source,
        connector=metadata.connector,
        risk=metadata.risk,
        required_config=metadata.required_config,
        mutates_state=metadata.mutates_state,
        approval_required=metadata.approval_required,
        implementation_module=str(getattr(tool_class, "__module__", "")),
        implementation_class=str(getattr(tool_class, "__name__", "")),
    )


def register_tool(tool_instance: Any):
    tool_name = str(tool_instance.name)
    TOOL_REGISTRY[tool_name] = tool_instance
    TOOL_REGISTRY_ENTRIES[tool_name] = _registry_entry_for_tool(tool_instance)


for tool_cls in [
    *TOOL_CLASSES_OPS_TRACKERS,
    *TOOL_CLASSES_CONNECTORS,
    *TOOL_CLASSES_WORKSPACE,
    *TOOL_CLASSES_WORKFLOW,
    *TOOL_CLASSES_AUX,
]:
    register_tool(tool_cls())


def get_tool_registry_entry(tool_name: str) -> dict[str, Any] | None:
    entry = TOOL_REGISTRY_ENTRIES.get(str(tool_name or "").strip())
    return entry.to_dict() if entry is not None else None


def list_tool_registry_entries(
    *,
    owner_type: str | None = None,
    source: str | None = None,
    connector: str | None = None,
) -> list[dict[str, Any]]:
    normalized_owner = str(owner_type or "").strip()
    normalized_source = str(source or "").strip()
    normalized_connector = str(connector or "").strip()
    entries = sorted(TOOL_REGISTRY_ENTRIES.values(), key=lambda item: item.name)
    result: list[dict[str, Any]] = []
    for entry in entries:
        if normalized_owner and entry.owner_type != normalized_owner:
            continue
        if normalized_source and entry.source != normalized_source:
            continue
        if normalized_connector and entry.connector != normalized_connector:
            continue
        result.append(entry.to_dict())
    return result


def get_tool_registry_owner_summary() -> dict[str, Any]:
    entries = list(TOOL_REGISTRY_ENTRIES.values())
    owner_counts = Counter(entry.owner_type for entry in entries)
    source_counts = Counter(entry.source for entry in entries)
    connector_counts = Counter(entry.connector for entry in entries if entry.connector)
    return {
        "total": len(TOOL_REGISTRY_ENTRIES),
        "owner_counts": dict(sorted(owner_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "connector_counts": dict(sorted(connector_counts.items())),
    }


async def _dispatch_registered_tool(tool_name: str, params: dict, context: ToolContext) -> dict:
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return annotate_tool_result_payload(
            tool_name,
            {"error": f"Unknown tool: {tool_name}"},
            category="unknown_tool",
            reason="not_registered",
        )
    try:
        # Reads of connectors with a configured web URL name their item pages as sources.
        # A call of a scope served by a named connection runs with that connection's config.
        from ..services.execution_runtime.command_audit import CommandActor, command_actor

        # Every server command this tool call causes is audited as this person's.
        with command_actor(CommandActor(db=getattr(context, "db", None), user_id=getattr(context, "user_id", None),
                                        session_id=getattr(context, "session_id", None), tool_name=tool_name)):
            result = await routed_execute(tool_name, params, context, tool.execute)
        if getattr(context, "chat_write_plan_calls", None):
            from ..services.run_capability.chat_write_plan import record_plan_created

            # What a plan-admitted write created (an issue, a branch) is in the plan's scope from now on.
            plan_note = await record_plan_created(tool_name, params, result, context)
            if plan_note and isinstance(result, dict):
                result = {**result, "write_plan": plan_note}
        result = link_configured_web_sources(tool_name, result, getattr(context, "project_config", None))
        return annotate_tool_result_payload(tool_name, result)
    except Exception as e:
        return annotate_tool_result_payload(
            tool_name,
            {"error": f"Tool execution failed: {safe_tool_error_message(e)}"},
            category="execution_error",
            reason="tool_exception",
        )


def unfenced_arguments(params: Any) -> Any:
    from ..services.content_security.knowledge_fence import unfenced_result

    return unfenced_result(params)


async def execute_tool(tool_name: str, params: dict, context: ToolContext) -> dict:
    params = await marked_arguments(tool_name, unfenced_arguments(params), context)
    blocked = await _run_governed_tool_checks(tool_name, params, context)
    if blocked is not None:
        return blocked
    result = await _dispatch_registered_tool(tool_name, params, context)
    return await content_checked(tool_name, _without_echoed_secrets(result, params), context)


def get_tool_definitions(agent_type: str = "change") -> list[dict]:
    """Return OpenRouter-compatible tool definitions filtered by agent_type (service-only tools are never offered)."""
    definitions = get_all_definitions()

    return [
        definition
        for name, definition in definitions.items()
        if name not in SERVICE_ONLY_TOOLS and is_tool_definition_available_for_agent_type(name, agent_type)
    ]


def get_all_tools_with_plugins(agent_type: str = "diagnosis") -> list[dict]:
    """Return all tool definitions including plugins."""
    base_tools = get_tool_definitions(agent_type)

    plugin_tools: list[dict] = []
    try:
        from ..plugins.core.manager import get_plugin_tools, load_plugins

        load_plugins()
        plugin_tools = get_plugin_tools()
    except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
        pass

    return base_tools + plugin_tools


async def execute_tool_with_plugins(tool_name: str, params: dict, context: ToolContext) -> dict:
    """Execute a tool (MCP tools first, then plugins, then built-in tools); its result passes the content check."""
    params = await marked_arguments(tool_name, unfenced_arguments(params), context)
    result = await _execute_tool_with_plugins(tool_name, params, context)
    return await content_checked(tool_name, _without_echoed_secrets(result, params), context)


def _without_echoed_secrets(result: Any, params: dict) -> Any:
    from ..services.secret_masking import mask_echoed_arguments

    return mask_echoed_arguments(result, params)


async def _execute_tool_with_plugins(tool_name: str, params: dict, context: ToolContext) -> dict:
    try:
        from ..plugins.core.manager import refresh_plugin_tool_metadata

        refresh_plugin_tool_metadata()
    except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
        pass
    if tool_name.startswith("rest__") and getattr(context, "db", None) is not None:
        # A custom REST operation is a database row: the gates below judge it as stored now (read or write, class).
        from ..services.rest_connector.tool_surface import refresh_rest_tool

        await refresh_rest_tool(context.db, tool_name)
    blocked = await _run_governed_tool_checks(tool_name, params, context)
    if blocked is not None:
        return blocked
    connector_db = getattr(context, "db", None)
    connector_name, blocked = await _breaker_gate(tool_name, context, connector_db)
    if blocked is not None:
        return blocked

    if tool_name.startswith("mcp__"):  # mcp__{server}__{tool}
        result, final = await _execute_mcp_tool(tool_name, params, context)
        if final:
            return result
        if connector_name and connector_db is not None:
            await _record_breaker(connector_db, connector_name, result)
        mcp_category = str(result.get("error_category") or "").strip() if isinstance(result, dict) else ""
        mcp_reason = str(result.get("reason") or "").strip() if isinstance(result, dict) else ""
        inactive = isinstance(result, dict) and result.get("error_category") == "inactive_server"
        mcp_policy = "mcp_access_policy" if inactive else None
        return annotate_tool_result_payload(tool_name, result, category=mcp_category or None,
                                            reason=mcp_reason or None, policy=mcp_policy)

    plugin_result = await _execute_plugin_tool(tool_name, params, context, connector_name, connector_db)
    if plugin_result is not None:
        return plugin_result
    if tool_name.startswith("database_tool_"):
        return await _execute_database_tool(tool_name, params, context)
    if tool_name.startswith("rest__"):
        return await _execute_rest_tool(tool_name, params, context)
    result = await _dispatch_registered_tool(tool_name, params, context)
    if connector_name and connector_db is not None:
        await _record_breaker(connector_db, connector_name, result)
    return result


