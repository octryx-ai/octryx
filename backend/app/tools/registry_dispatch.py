"""Where a tool call goes after its checks: MCP servers, plugins, database and REST tools, the circuit breaker."""

from typing import Any

from ..services.mcp_access_policy import (
    blocked_mcp_server_result,
    blocked_mcp_tool_result,
    mcp_access_for_context,
    mcp_tool_allowed,
)
from .context import ToolContext
from .results import annotate_tool_result_payload, safe_tool_error_message


async def _breaker_gate(tool_name: str, context: ToolContext, connector_db: Any) -> tuple[str | None, dict | None]:
    # (the call's breaker key ``<connector>@<scope>``, the refusal while its breaker is open)
    if connector_db is None:
        return None, None
    try:
        from ..services.circuit_breaker import check_circuit_breaker
        from ..services.connector_health.breaker_scope import tool_call_breaker_key

        connector_name = await tool_call_breaker_key(connector_db, tool_name, context)
        if connector_name:
            decision = await check_circuit_breaker(connector_db, connector_name)
            if not decision.allowed:
                return connector_name, annotate_tool_result_payload(
                    tool_name,
                    {"error": decision.reason, "connector_name": connector_name,
                     "circuit_breaker_state": decision.state, "next_retry_at": decision.next_retry_at},
                    category="provider_unavailable",
                    reason=str(decision.state or "circuit_breaker_blocked"),
                    policy="circuit_breaker",
                    retryable=bool(decision.next_retry_at),
                )
        return connector_name, None
    except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
        return None, None


async def _execute_mcp_tool(tool_name: str, params: dict, context: ToolContext) -> tuple[Any, bool]:
    # (result, final): a final result is a refusal answered as is, never counted for the circuit breaker.
    try:
        from ..plugins.mcp.client import mcp_client_manager

        parts = tool_name.split("__", 2)
        if len(parts) != 3:
            return annotate_tool_result_payload(tool_name, {"error": f"Invalid MCP tool name format: {tool_name}"},
                                                category="invalid_name", reason="invalid_mcp_tool_name"), True
        _, server_name, tool_name_only = parts
        refused = await _mcp_refusal(tool_name, server_name, tool_name_only, context)
        if refused is not None:
            return refused, True
        from .mcp_registry_dispatch import dispatch_registered_mcp_tool

        return await dispatch_registered_mcp_tool(context=context, mcp_client_manager=mcp_client_manager,
                                                  server_name=server_name, tool_name=tool_name_only,
                                                  arguments=params), False
    except (ImportError, RuntimeError, ValueError, TypeError, OSError) as e:
        return annotate_tool_result_payload(
            tool_name,
            {"error": f"MCP tool execution failed: {safe_tool_error_message(e)}"},
            category="provider_failure",
            reason="mcp_tool_execution_failed",
        ), False


async def _mcp_refusal(tool_name: str, server_name: str, tool_name_only: str, context: ToolContext) -> dict | None:
    access = mcp_access_for_context(server_name, context)
    if not access.allowed:
        return annotate_tool_result_payload(tool_name, blocked_mcp_server_result(access), category="denied_by_policy",
                                            reason=access.reason, policy="mcp_access_policy")
    if not mcp_tool_allowed(server_name, tool_name_only, context.project_config):
        return annotate_tool_result_payload(tool_name, blocked_mcp_tool_result(server_name, tool_name_only),
                                            category="denied_by_policy", reason="mcp_tool_not_selected",
                                            policy="mcp_access_policy")
    # Deny-before-dispatch guarantee: a disabled or unbound capability must never reach the remote MCP server.
    from ..services.mcp_capability_gate import mcp_capability_dispatch_block

    capability_block = await mcp_capability_dispatch_block(server_name=server_name, tool_name=tool_name_only,
                                                           context=context)
    if capability_block is not None:
        return annotate_tool_result_payload(tool_name, capability_block, category="denied_by_policy",
                                            reason=str(capability_block.get("reason") or ""),
                                            policy="mcp_capability_policy")
    return None


async def _execute_plugin_tool(tool_name: str, params: dict, context: ToolContext, connector_name: str | None,
                               connector_db: Any) -> dict | None:
    # The plugin's annotated result, or None when no plugin offers this tool (or it failed: the next kind is tried).
    try:
        from ..plugins.core.manager import execute_plugin_tool, get_model_visible_plugin_tool_names

        if tool_name not in get_model_visible_plugin_tool_names():
            return None
        plugin_result = await execute_plugin_tool(tool_name, params, context)
        plugin_category = (str(plugin_result.get("error_category") or "").strip()
                           if isinstance(plugin_result, dict) else "")
        plugin_reason = str(plugin_result.get("reason") or "").strip() if isinstance(plugin_result, dict) else ""
        result = annotate_tool_result_payload(tool_name, plugin_result, category=plugin_category or None,
                                              reason=plugin_reason or None)
        if connector_name and connector_db is not None:
            await _record_breaker(connector_db, connector_name, result)
        return result
    except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
        return None


async def _execute_database_tool(tool_name: str, params: dict, context: ToolContext) -> dict:
    try:
        from ..services.database_tool_service import execute_database_query_tool

        return annotate_tool_result_payload(tool_name, await execute_database_query_tool(tool_name, params, context))
    except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
        return annotate_tool_result_payload(
            tool_name,
            {"error": f"Database tool execution failed: {safe_tool_error_message(exc)}"},
            category="provider_error",
            reason="database_tool_execution_failed",
        )


async def _execute_rest_tool(tool_name: str, params: dict, context: ToolContext) -> dict:
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


async def _record_breaker(connector_db: Any, connector_name: str, result: Any) -> None:
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
