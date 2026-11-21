from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.services.agent_tool_surface_decision import apply_tool_surface_decision_to_profile, evaluate_agent_tool_surface
from app.services.execution_profile_trace import execution_profile_trace_summary
from app.tools.context import ToolContext

from ....services.execution_profile_offered_tools import (
    apply_offered_tool_decision_to_profile,
    evaluate_offered_definition_tools,
)
from ....services.run_capability.chat_writes import chat_connector_write_permitted
from ....services.tool_access_policy import filter_tool_definitions_for_project_policy
from ....tools.visibility import filter_tool_definitions_by_visibility
from ...loops.response._loop_reply_contract import (
    apply_reply_contract_admission_to_profile,
    evaluate_reply_contract_admission,
)
from ..guards.response_guards import get_step_allowed_tools
from ..types import ToolDefinition
from .run_context_tool_policy import (
    apply_routing_tool_policy,
    routing_policy_prefilter_tool_names,
    tool_name_of,
    unique_tool_names,
)
from .turn_tool_surface import workflow_declares_tool_surface

FilterToolDefinitions = Callable[[list[ToolDefinition], list[str]], list[ToolDefinition]]
ExcludeToolDefinitions = Callable[[list[ToolDefinition], list[str]], list[ToolDefinition]]
GetAllTools = Callable[..., list[ToolDefinition]]
DynamicDatabaseToolLoader = Callable[[Any, ToolContext], Awaitable[list[ToolDefinition]]]
DYNAMIC_DATABASE_CATALOG_METADATA_KEY = "dynamic_database_catalog"


def _record_dynamic_database_catalog_state(
    tool_context: ToolContext,
    *,
    status: str,
    reason: str,
    tool_count: int = 0,
    fail_closed: bool = False,
    error: BaseException | None = None,
) -> None:
    metadata = dict(tool_context.tooling_metadata or {})
    catalog_state: dict[str, Any] = {
        "source": "database_tool_registry",
        "status": status,
        "reason": reason,
        "tool_count": int(tool_count),
        "fail_closed": bool(fail_closed),
    }
    if error is not None:
        catalog_state["error_type"] = type(error).__name__
    metadata[DYNAMIC_DATABASE_CATALOG_METADATA_KEY] = catalog_state
    tool_context.tooling_metadata = metadata


def _apply_final_tool_policies(
    tool_definitions: list[ToolDefinition],
    *,
    tool_context: ToolContext,
    workflow_routing_policy_resolution: dict[str, Any] | None,
) -> list[ToolDefinition]:
    visible_definitions = filter_tool_definitions_by_visibility(
        tool_definitions,
        tool_context.project_config,
    )
    routed_definitions = apply_routing_tool_policy(
        visible_definitions,
        routing_resolution=workflow_routing_policy_resolution,
    )
    from ....services.work_role_model.surfaces import filter_definitions

    # A chat turn's work-role grant narrows like the other final policies (``None``: nothing narrows).
    routed_definitions = filter_definitions(routed_definitions, getattr(tool_context, "work_role_grant", None))
    return filter_tool_definitions_for_project_policy(
        routed_definitions,
        tool_context.project_config,
        # A chat's connector writes are confirmed (one write plan per request): offered as the dispatch admits them.
        confirmed_per_call=lambda tool_name: chat_connector_write_permitted(tool_name, tool_context),
    )


async def _load_full_tool_definitions(
    db: Any,
    *,
    tool_context: ToolContext,
    capability_type: str,
    include_tools: bool,
    get_all_tools_with_plugins: GetAllTools,
    list_dynamic_database_tool_definitions: DynamicDatabaseToolLoader | None,
) -> list[ToolDefinition]:
    """Every tool the turn could be offered: the registry and plugins, plus the database tool catalog."""
    full_tool_definitions = get_all_tools_with_plugins(agent_type=capability_type) if include_tools else []

    if include_tools and list_dynamic_database_tool_definitions is not None:
        try:
            dynamic_tool_definitions = await list_dynamic_database_tool_definitions(db, tool_context)
            _record_dynamic_database_catalog_state(
                tool_context,
                status="loaded",
                reason="catalog_loaded",
                tool_count=len(dynamic_tool_definitions),
            )
        except Exception as exc:
            _record_dynamic_database_catalog_state(
                tool_context,
                status="unavailable",
                reason="catalog_load_failed",
                fail_closed=True,
                error=exc,
            )
            dynamic_tool_definitions = []
        full_tool_definitions = full_tool_definitions + dynamic_tool_definitions
    elif include_tools:
        _record_dynamic_database_catalog_state(
            tool_context,
            status="unavailable",
            reason="loader_not_configured",
            fail_closed=True,
        )
    return full_tool_definitions


def _add_agent_step_tools(
    tool_definitions: list[ToolDefinition],
    *,
    full_tool_definitions: list[ToolDefinition],
    step_allowed_tools: list[str],
    filter_tool_definitions: FilterToolDefinitions,
) -> None:
    """Append the tools the agent's enabled steps allow that the filters above dropped."""
    existing_tool_names = {
        definition.get("function", {}).get("name")
        for definition in tool_definitions
        if definition.get("function", {}).get("name")
    }
    for definition in filter_tool_definitions(full_tool_definitions, step_allowed_tools):
        tool_name = tool_name_of(definition)
        if tool_name and tool_name not in existing_tool_names:
            tool_definitions.append(definition)
            existing_tool_names.add(tool_name)


def _enabled_step_tools(agent_definition: dict[str, Any]) -> list[str]:
    return sorted(
        {
            tool_name
            for step in agent_definition.get("steps", [])
            if step.get("isEnabled") or step.get("is_enabled")
            for tool_name in get_step_allowed_tools(step)
        }
    )


async def build_run_context_tool_definitions(
    *,
    db: Any,
    tool_context: ToolContext,
    capability_type: str,
    include_tools: bool,
    tool_allowlist: list[str],
    blocked_tools: list[str],
    agent_definition: dict[str, Any] | None,
    get_all_tools_with_plugins: GetAllTools,
    filter_tool_definitions: FilterToolDefinitions,
    exclude_tool_definitions: ExcludeToolDefinitions,
    list_dynamic_database_tool_definitions: DynamicDatabaseToolLoader | None = None,
    workflow_routing_policy_resolution: dict[str, Any] | None = None,
) -> list[ToolDefinition]:
    full_tool_definitions = await _load_full_tool_definitions(
        db,
        tool_context=tool_context,
        capability_type=capability_type,
        include_tools=include_tools,
        get_all_tools_with_plugins=get_all_tools_with_plugins,
        list_dynamic_database_tool_definitions=list_dynamic_database_tool_definitions,
    )
    tool_definitions = list(full_tool_definitions)
    effective_tool_allowlist = list(tool_allowlist or [])
    if effective_tool_allowlist:
        available_tool_names = [tool_name_of(definition) for definition in full_tool_definitions]
        effective_tool_allowlist = unique_tool_names(
            [
                *effective_tool_allowlist,
                *routing_policy_prefilter_tool_names(
                    routing_resolution=workflow_routing_policy_resolution,
                    available_tool_names=available_tool_names,
                ),
            ]
        )
        tool_definitions = filter_tool_definitions(tool_definitions, effective_tool_allowlist)
    if blocked_tools:
        tool_definitions = exclude_tool_definitions(tool_definitions, blocked_tools)
    agent_denied = sorted((agent_definition or {}).get("toolsDeny") or [])
    if agent_denied:  # also when the turn has no allowlist (dispatch refuses them as well)
        tool_definitions = exclude_tool_definitions(tool_definitions, agent_denied)
    step_allowed_tools = _enabled_step_tools(agent_definition) if agent_definition and include_tools else []
    if step_allowed_tools:
        _add_agent_step_tools(
            tool_definitions,
            full_tool_definitions=full_tool_definitions,
            step_allowed_tools=step_allowed_tools,
            filter_tool_definitions=filter_tool_definitions,
        )
    return _apply_final_tool_policies(
        tool_definitions,
        tool_context=tool_context,
        workflow_routing_policy_resolution=workflow_routing_policy_resolution,
    )


def record_offered_tool_decision(
    *,
    session_metadata: dict[str, Any],
    current_session: Any,
    tool_context: ToolContext,
    routing_resolution: dict[str, Any] | None,
    workflow_contract: dict[str, Any] | None,
    tool_definitions: list[ToolDefinition],
    workflow_id: str | None = None,
    agent_definition: dict[str, Any] | None = None,
) -> None:
    """Hold a turn whose agent tool setting conflicts, whose agent reply format is invalid or
    cannot be checked on this path, or whose selected definition's offered tools miss what it
    declares.

    The decision lands on the turn's execution profile (session metadata and the tool
    context's trace summary), so the execution gate blocks the turn before any model call.
    The agent decision goes first: a blocked profile keeps its earlier, more specific reason.
    """
    surface_decision = evaluate_agent_tool_surface(
        agent_definition,
        workflow_tools_declared=workflow_declares_tool_surface(
            workflow_id=workflow_id, workflow_contract=workflow_contract, routing_resolution=routing_resolution
        ),
    )
    session_metadata["execution_profile"] = apply_tool_surface_decision_to_profile(
        session_metadata.get("execution_profile"), surface_decision
    )
    reply_admission = evaluate_reply_contract_admission(
        agent_definition,
        session_metadata.get("execution_profile"),
        workflow_id=workflow_id,
        # After admission ``run_agent`` would hand these turns to the flow orchestrator.
        delegated_runtime=bool(getattr(current_session, "flow_definition_version_id", None)),
    )
    session_metadata["execution_profile"] = apply_reply_contract_admission_to_profile(
        session_metadata.get("execution_profile"), reply_admission
    )
    decision = evaluate_offered_definition_tools(
        routing_resolution=routing_resolution,
        workflow_contract=workflow_contract,
        tool_definitions=tool_definitions,
        project_config=tool_context.project_config,
    )
    profile = apply_offered_tool_decision_to_profile(session_metadata.get("execution_profile"), decision)
    session_metadata["execution_profile"] = profile
    tool_context.execution_profile_trace = execution_profile_trace_summary(profile)
    reply_allowed = reply_admission is None or reply_admission.allowed
    if current_session is not None and not (decision.satisfied and surface_decision.allowed and reply_allowed):
        # ``session_metadata`` is the flushed metadata object itself, so the in-place profile
        # change is invisible to change detection: mark the column modified explicitly.
        current_session.metadata_ = dict(session_metadata)
        flag_modified(current_session, "metadata_")
