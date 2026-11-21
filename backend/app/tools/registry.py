"""Tool registry – maps tool names to implementations."""

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from app.tools.registry_impl._registry_toolset_connectors import TOOL_CLASSES_CONNECTORS
from app.tools.registry_impl._registry_toolset_ops_trackers import TOOL_CLASSES_OPS_TRACKERS
from app.tools.registry_impl._registry_toolset_workflow import TOOL_CLASSES_WORKFLOW
from app.tools.registry_impl._registry_toolset_workspace import TOOL_CLASSES_WORKSPACE

from ..services.decisions.tool_dispatch import recorded_tool_dispatch
from ..services.mcp_access_policy import (
    blocked_mcp_server_result,
    blocked_mcp_tool_result,
    mcp_access_for_context,
    mcp_tool_allowed,
)
from ..services.named_connections.tool_routing import routed_execute
from ..services.tool_access_policy import blocked_tool_result, tool_project_policy_decision
from .connectors.web_url_sources import link_configured_web_sources
from .context import ToolContext
from .definitions import get_all_definitions, get_tool_definition_metadata, is_tool_definition_available_for_agent_type
from .definitions.connector_ownership import SERVICE_ONLY_TOOLS
from .registry_impl._registry_toolset_aux import TOOL_CLASSES_AUX
from .result_content import content_checked
from .results import annotate_tool_result_payload, safe_tool_error_message
from .visibility import blocked_inactive_connector_tool_result


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


def _chat_write_answers_explicit_allow(tool_name: str, context: ToolContext, decision: Any) -> bool:
    """A chat's connector write is confirmed by the person (``run_capability/chat_writes.py``; one write
    plan per request since ``chat_write_plan.py``).

    That confirmation is the explicit allow the high-risk rule asks for; a Workspace deny list or allow rules that
    leave the tool out still refuse."""
    from ..services.run_capability.chat_writes import chat_connector_write_permitted
    from ..services.tool_access_policy_rules import HIGH_RISK_EXPLICIT_ALLOW_REASON

    return (not decision.allowed and decision.reason == HIGH_RISK_EXPLICIT_ALLOW_REASON
            and chat_connector_write_permitted(tool_name, context))


def _is_chat_connector_write(tool_name: str, context: ToolContext) -> bool:
    from ..services.run_capability.chat_writes import chat_connector_write_permitted

    return chat_connector_write_permitted(tool_name, context)


@recorded_tool_dispatch
async def _run_governed_tool_checks(tool_name: str, params: dict, context: ToolContext) -> dict | None:
    """Shared governance for every dispatch entrypoint; the outcome is a decision record or an allow count (O2)."""
    from ..services.workflow_runs.handoff.lifecycle import guard_tool_context
    from ..services.workflow_runs.records import WorkflowRunError

    try:
        await guard_tool_context(context)
    except WorkflowRunError as error:
        return {"status": "refused", "reason": error.code, "error": str(error)}
    # An agent set to No tools (text only) runs no tool at all, whatever the model or the
    # platform asked for. Imported lazily like the gates below.
    from app.services.agent_tool_surface_decision import tool_surface_dispatch_refusal

    surface_refusal = tool_surface_dispatch_refusal(tool_name, context)
    if surface_refusal is not None:
        return surface_refusal
    # The published agent's tools deny refuses at dispatch too, not only in the model's view.
    from ..services.agent_tools_deny import agent_tools_deny_refusal

    deny_refusal = agent_tools_deny_refusal(tool_name, context)
    if deny_refusal is not None:
        return deny_refusal
    # A chat turn calls only what the person's work roles grant; named, never silent.
    from ..services.work_role_model.surfaces import dispatch_refusal

    role_refusal = dispatch_refusal(tool_name, context)
    if role_refusal is not None:
        return annotate_tool_result_payload(tool_name, role_refusal, category="denied_by_policy",
                                            reason=role_refusal.get("code"), policy=str(role_refusal["policy"]))
    blocked_by_visibility = blocked_inactive_connector_tool_result(tool_name, context.project_config)
    if blocked_by_visibility is None:
        # The classification level also judges the call's arguments (``run_kubectl logs``).
        from ..services.classification_tool_policy import classification_tool_refusal

        blocked_by_visibility = classification_tool_refusal(tool_name, context.project_config, params)
    if (blocked_by_visibility is not None and getattr(context, "workflow_platform_action", False)
            and blocked_by_visibility.get("code") in {"connection_agent_tools_read_only",
                                                      "connection_agent_tools_off"}):
        # The connection's agent tools level governs agents; a published workflow's own typed platform action is not
        # an agent tool call (otherwise scm.create_branch was refused on a "Tools: read" Bitbucket connection).
        blocked_by_visibility = None
    if blocked_by_visibility is not None:
        return annotate_tool_result_payload(
            tool_name,
            blocked_by_visibility,
            category="denied_by_policy",
            reason=blocked_by_visibility.get("reason"),
            policy=str(blocked_by_visibility.get("policy") or "connector_activation"),
        )
    policy_decision = tool_project_policy_decision(tool_name, context.project_config)
    if (not policy_decision.allowed and getattr(context, "workflow_platform_action", False)
            and policy_decision.reason == "high_risk_tool_requires_explicit_allow"):
        # A published workflow's own platform action is explicitly allowed by that workflow (otherwise Jira intake
        # could not post its questions by default). Project deny lists and deny patterns still refuse.
        policy_decision = None
    if policy_decision is not None and _chat_write_answers_explicit_allow(tool_name, context, policy_decision):
        policy_decision = None
    if policy_decision is not None and not policy_decision.allowed:
        return annotate_tool_result_payload(
            tool_name,
            blocked_tool_result(tool_name, policy_decision),
            category="denied_by_policy",
            reason=policy_decision.reason,
            policy=policy_decision.policy,
        )
    # The run capability refuses a tool that exceeds the run's class before any
    # MCP or approval check. Imported lazily like the gates below.
    from ..services.run_capability.escalation import CAPABILITY_REFUSAL_POLICY, capability_dispatch_refusal

    capability_refusal = capability_dispatch_refusal(tool_name, context)
    if capability_refusal is not None:
        return annotate_tool_result_payload(
            tool_name, capability_refusal, category="denied_by_policy", policy=CAPABILITY_REFUSAL_POLICY
        )
    # Imported lazily: the approval gate pulls in approval/notification services
    # whose import chains must not run at registry module load time.
    from ..services.mcp_capability_gate import evaluate_mcp_capability_dispatch
    from ..services.mcp_resource_dispatch import evaluate_mcp_resource_dispatch, finalize_mcp_resource_dispatch
    from ..services.tool_approval_gate import enforce_tool_approval

    # MCP governance sits between tool policy and approval: server activation
    # first, then the workspace capability binding, then approval carrying the
    # explicit capability subject instead of the generic bridge identity. Mirrored
    # tools and governed resources/prompts are disjoint tool sets with their own
    # catalogs, so at most one of the two gates ever resolves a subject.
    mcp_gate = await evaluate_mcp_capability_dispatch(tool_name, params, context)
    if mcp_gate.blocked_result is not None:
        return annotate_tool_result_payload(
            tool_name,
            mcp_gate.blocked_result,
            category="denied_by_policy",
            reason=mcp_gate.blocked_reason,
            policy=mcp_gate.blocked_policy,
        )
    resource_gate = await evaluate_mcp_resource_dispatch(tool_name, params, context)
    if resource_gate.blocked_result is not None:
        return annotate_tool_result_payload(
            tool_name,
            resource_gate.blocked_result,
            category="denied_by_policy",
            reason=resource_gate.blocked_reason,
            policy=resource_gate.blocked_policy,
        )
    if mcp_gate.approval_subject is None and resource_gate.approval_subject is None and _is_chat_connector_write(
            tool_name, context):
        from ..services.tool_approval_previews import chat_write_route_refusal

        # A chat write its connection plan refuses is answered now, never put to the person to confirm first.
        route_refusal = chat_write_route_refusal(tool_name, params, context.project_config)
        if route_refusal is not None:
            return annotate_tool_result_payload(tool_name, route_refusal, category="denied_by_policy",
                                                reason=route_refusal.get("code"), policy="connection_routing")
    approval_result = await enforce_tool_approval(
        tool_name,
        params,
        context,
        subject=mcp_gate.approval_subject or resource_gate.approval_subject,
    )
    from ..services.coding_dispatch_gates import enforce_coding_dispatch_gates

    # Delivery proof and upgrade gate order; the result arrives annotated with the refusing gate.
    delivery_block = (
        None if approval_result is not None else await enforce_coding_dispatch_gates(tool_name, params, context)
    )
    # The governed resource request is closed out once every gate has answered: a
    # hold or a later block is final and is audited here, while a request that
    # actually proceeds is only marked as already-governed, so the tool — not this
    # gate — records whether anything executed.
    await finalize_mcp_resource_dispatch(
        resource_gate,
        context,
        tool_name=tool_name,
        approval_held=approval_result is not None,
        blocked_downstream=delivery_block is not None,
    )
    if approval_result is not None and approval_result.get("next_tool"):
        # The chat's write plan does not cover this call: no one is asked, the model is told its next step.
        from ..services.run_capability.chat_write_plan import PLAN_POLICY

        return annotate_tool_result_payload(tool_name, approval_result, category="denied_by_policy",
                                            reason=approval_result.get("code"), policy=PLAN_POLICY)
    if approval_result is not None:
        return annotate_tool_result_payload(
            tool_name,
            approval_result,
            category="approval_required",
            policy="tool_approval_gate",
        )
    return delivery_block


async def _dispatch_registered_tool(tool_name: str, params: dict, context: ToolContext) -> dict:
    """Execute a registered tool without governance checks; callers gate first."""
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
    """A call's arguments without fence markers, before any gate, preview or fingerprint sees them.

    Fence only at the entrance to a model, never at an exit: a model copies fenced text it
    read (``<<<summary …>>>`` from a live Jira read) into a write's arguments, and a flow passes a fenced tool output
    on as the next step's arguments. Stripped here, every write (Jira/ServiceNow/REST, PR titles and comments, Work
    item fields, Teams/Slack and notification tools) carries the body only, and the approval the person sees and its
    fingerprint describe exactly what runs. Arguments without markers pass as the same object."""
    from ..services.content_security.knowledge_fence import unfenced_result

    return unfenced_result(params)


async def execute_tool(tool_name: str, params: dict, context: ToolContext) -> dict:
    params = unfenced_arguments(params)
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
    """Return all tool definitions including plugins.

    MCP servers are exposed lazily through the native bridge tools
    `list_mcp_servers`, `list_mcp_server_tools`, and `call_mcp_server_tool`
    instead of injecting one function schema per MCP tool into every prompt.
    """
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
    params = unfenced_arguments(params)
    result = await _execute_tool_with_plugins(tool_name, params, context)
    return await content_checked(tool_name, _without_echoed_secrets(result, params), context)


def _without_echoed_secrets(result: Any, params: dict) -> Any:
    """A secret the call itself carried never comes back to the model in the result (secret_masking)."""
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
    if tool_name.startswith("run_flow_"):
        from .flow_capability_dispatch import dispatch_flow_capability_tool

        return await dispatch_flow_capability_tool(tool_name, params, context)
    connector_name = None
    connector_db = getattr(context, "db", None)
    if connector_db is not None:
        try:
            from ..services.circuit_breaker import check_circuit_breaker
            from ..services.connector_health.breaker_scope import tool_call_breaker_key

            connector_name = await tool_call_breaker_key(connector_db, tool_name, context)  # <connector>@<scope>
            if connector_name:
                decision = await check_circuit_breaker(connector_db, connector_name)
                if not decision.allowed:
                    return annotate_tool_result_payload(
                        tool_name,
                        {
                            "error": decision.reason,
                            "connector_name": connector_name,
                            "circuit_breaker_state": decision.state,
                            "next_retry_at": decision.next_retry_at,
                        },
                        category="provider_unavailable",
                        reason=str(decision.state or "circuit_breaker_blocked"),
                        policy="circuit_breaker",
                        retryable=bool(decision.next_retry_at),
                    )
        except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
            connector_name = None

    # Check if this is an MCP tool (format: mcp__{server}__{tool})
    if tool_name.startswith("mcp__"):
        try:
            from ..plugins.mcp.client import mcp_client_manager

            # Parse server_name and tool_name_only from mcp__{server}__{tool}
            parts = tool_name.split("__", 2)
            if len(parts) == 3:
                _, server_name, tool_name_only = parts
                access = mcp_access_for_context(server_name, context)
                if not access.allowed:
                    return annotate_tool_result_payload(
                        tool_name,
                        blocked_mcp_server_result(access),
                        category="denied_by_policy",
                        reason=access.reason,
                        policy="mcp_access_policy",
                    )
                if not mcp_tool_allowed(server_name, tool_name_only, context.project_config):
                    return annotate_tool_result_payload(
                        tool_name,
                        blocked_mcp_tool_result(server_name, tool_name_only),
                        category="denied_by_policy",
                        reason="mcp_tool_not_selected",
                        policy="mcp_access_policy",
                    )
                # Deny-before-dispatch guarantee: a disabled or unbound
                # capability must never reach the remote MCP server.
                from ..services.mcp_capability_gate import mcp_capability_dispatch_block

                capability_block = await mcp_capability_dispatch_block(
                    server_name=server_name,
                    tool_name=tool_name_only,
                    context=context,
                )
                if capability_block is not None:
                    return annotate_tool_result_payload(
                        tool_name,
                        capability_block,
                        category="denied_by_policy",
                        reason=str(capability_block.get("reason") or ""),
                        policy="mcp_capability_policy",
                    )
                from .mcp_registry_dispatch import dispatch_registered_mcp_tool

                result = await dispatch_registered_mcp_tool(
                    context=context,
                    mcp_client_manager=mcp_client_manager,
                    server_name=server_name,
                    tool_name=tool_name_only,
                    arguments=params,
                )
            else:
                return annotate_tool_result_payload(
                    tool_name,
                    {"error": f"Invalid MCP tool name format: {tool_name}"},
                    category="invalid_name",
                    reason="invalid_mcp_tool_name",
                )
        except (ImportError, RuntimeError, ValueError, TypeError, OSError) as e:
            result = annotate_tool_result_payload(
                tool_name,
                {"error": f"MCP tool execution failed: {safe_tool_error_message(e)}"},
                category="provider_failure",
                reason="mcp_tool_execution_failed",
            )
        if connector_name and connector_db is not None:
            await _record_breaker(connector_db, connector_name, result)
        mcp_category = str(result.get("error_category") or "").strip() if isinstance(result, dict) else ""
        mcp_reason = str(result.get("reason") or "").strip() if isinstance(result, dict) else ""
        mcp_policy = (
            "mcp_access_policy"
            if isinstance(result, dict) and result.get("error_category") == "inactive_server"
            else None
        )
        return annotate_tool_result_payload(
            tool_name,
            result,
            category=mcp_category or None,
            reason=mcp_reason or None,
            policy=mcp_policy,
        )

    try:
        from ..plugins.core.manager import (
            execute_plugin_tool,
            get_model_visible_plugin_tool_names,
        )

        plugin_tool_names = get_model_visible_plugin_tool_names()

        if tool_name in plugin_tool_names:
            plugin_result = await execute_plugin_tool(tool_name, params, context)
            plugin_category = (
                str(plugin_result.get("error_category") or "").strip() if isinstance(plugin_result, dict) else ""
            )
            plugin_reason = str(plugin_result.get("reason") or "").strip() if isinstance(plugin_result, dict) else ""
            result = annotate_tool_result_payload(
                tool_name,
                plugin_result,
                category=plugin_category or None,
                reason=plugin_reason or None,
            )
            if connector_name and connector_db is not None:
                await _record_breaker(connector_db, connector_name, result)
            return result
    except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
        pass

    if tool_name.startswith("database_tool_"):
        try:
            from ..services.database_tool_service import execute_database_query_tool

            return annotate_tool_result_payload(
                tool_name,
                await execute_database_query_tool(tool_name, params, context),
            )
        except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
            return annotate_tool_result_payload(
                tool_name,
                {"error": f"Database tool execution failed: {safe_tool_error_message(exc)}"},
                category="provider_error",
                reason="database_tool_execution_failed",
            )

    if tool_name.startswith("rest__"):
        # Custom REST connector: authorization, data scope, the write's run class and audit live in the executor.
        try:
            from ..services.rest_connector.executor import execute_rest_tool

            rest_result = await execute_rest_tool(tool_name, params, context)
            code = str(rest_result.get("code") or "") if isinstance(rest_result, dict) else ""
            refused = code in {"not_granted", "scope_violation", "capability_exceeded"}
            return annotate_tool_result_payload(
                tool_name,
                rest_result,
                category="denied_by_policy" if refused else None,
                reason=code or None,
                policy="rest_api_grants" if refused else None,
            )
        except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
            return annotate_tool_result_payload(
                tool_name,
                {"error": f"REST API tool execution failed: {safe_tool_error_message(exc)}"},
                category="provider_error",
                reason="rest_tool_execution_failed",
            )

    result = await _dispatch_registered_tool(tool_name, params, context)
    if connector_name and connector_db is not None:
        await _record_breaker(connector_db, connector_name, result)
    return result


async def _record_breaker(connector_db: Any, connector_name: str, result: Any) -> None:
    """Count a tool result for its connector's circuit breaker: a real connector error is a failure, a denial by
    our own policy or configuration counts as nothing (``circuit_breaker.outcome``)."""
    try:
        from ..services.circuit_breaker import (
            record_circuit_breaker_failure,
            record_circuit_breaker_success,
        )
        from ..services.circuit_breaker.outcome import FAILURE, SUCCESS, breaker_outcome

        outcome = breaker_outcome(result)
        if outcome == FAILURE:
            await record_circuit_breaker_failure(connector_db, connector_name, str(result.get("error") or "tool_error"))
        elif outcome == SUCCESS:
            await record_circuit_breaker_success(connector_db, connector_name)
    except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
        pass
