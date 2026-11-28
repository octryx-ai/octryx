"""Route a connector tool call to the connection of its scope, for every descriptor connector."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from .contract import scope_key
from .descriptor import ConnectorDescriptor, UnitIncompleteError
from .descriptors import descriptor_of
from .resolver import connection_config, connection_name, connection_ref, with_secrets
from .route_plan import CONNECTION_PARAM, RoutePlan, refusal
from .route_plan import scope_keys as _plan_scope_keys
from .route_planner import plan_route
from .routes_model import REASON_NOT_CONFIGURED_FOR_SCOPE, NamedConnectionRoutes, ResolvedNamedConnection, routes_of
from .runtime_state import note_tool_result

logger = logging.getLogger(__name__)

Execute = Callable[[dict, Any], Awaitable[Any]]
REASON_CREDENTIAL_UNAVAILABLE = "named_connection_credential_unavailable"
REASON_REQUEST_NOT_ALLOWED = "named_connection_request_not_allowed"


def scope_keys(tool: str, tool_name: str, params: dict) -> tuple[str, ...]:
    descriptor = descriptor_of(tool)
    return _plan_scope_keys(descriptor, tool_name, params) if descriptor is not None else ()


def _guarded(descriptor: ConnectorDescriptor, connection: ResolvedNamedConnection | None, config: dict,
             tool_name: str, params: dict) -> dict[str, Any] | None:
    if connection is None:
        return None
    label = {"connection": connection.name, "connection_id": connection.id}
    if descriptor.runtime_guard is not None:
        try:
            descriptor.runtime_guard(config)
        except UnitIncompleteError as incomplete:
            return refusal(REASON_CREDENTIAL_UNAVAILABLE, descriptor.connector,
                           f"The named connection cannot run this call: {incomplete}", **label)
    if descriptor.request_guard is not None:
        problem = descriptor.request_guard(tool_name, config, params)
        if problem:
            return refusal(REASON_REQUEST_NOT_ALLOWED, descriptor.connector, problem, **label)
    return None


async def _run_on(
    plan: RoutePlan, routes: NamedConnectionRoutes, base: dict, connection: ResolvedNamedConnection | None,
    tool_name: str, params: dict, context: Any, execute: Execute,
) -> Any:
    tool = plan.descriptor.connector
    from ..work_role_model.surfaces import write_connection_refusal

    # Delivery per connection: the routed connection, never one named in an argument, decides.
    role_refused = write_connection_refusal(tool_name, context, connection_ref(connection),
                                            connection_name(connection))
    if role_refused is not None:
        return role_refused
    if connection is not None:
        connection = await with_secrets(getattr(context, "db", None), connection)
    config = connection_config(base, tool, routes, connection)
    refused = _guarded(plan.descriptor, connection, config, tool_name, params)
    if refused is not None:
        return refused
    out = await execute(params, _on_connection(context, config, connection))
    await note_tool_result(getattr(context, "db", None), routes, tool, connection, out)
    return out


def _on_connection(context: Any, config: dict, connection: ResolvedNamedConnection | None) -> Any:
    if hasattr(context, "connection_id"):
        return replace(context, project_config=config, connection_id=connection_ref(connection))
    return replace(context, project_config=config)


async def _fan_out(
    plan: RoutePlan, routes: NamedConnectionRoutes, base: dict, tool_name: str, params: dict, context: Any,
    execute: Execute,
) -> dict[str, Any]:
    descriptor = plan.descriptor
    tool = descriptor.connector
    bound = routes.bound_keys(tool)
    merged: dict[str, Any] | None = None
    results: list[Any] = []
    summary: list[dict[str, Any]] = [dict(item) for item in plan.skipped]
    for connection in plan.targets:
        out = await _run_on(plan, routes, base, connection, tool_name, params, context, execute)
        label = {"connection": connection_name(connection), "connection_id": connection_ref(connection)}
        if not isinstance(out, dict) or "error" in out:
            error = out.get("error") if isinstance(out, dict) else "unexpected result"
            summary.append({**label, "error": error})
            continue
        found = [item for item in out.get("results") or []]
        if connection is None and descriptor.result_key is not None:
            # An unrestricted default never reports an item of a bound key (read by its own account).
            found = [item for item in found if scope_key(tool, descriptor.result_key(item) or "") not in bound]
        results.extend(found)
        summary.append({**label, "count": len(found)})
        merged = merged or {key: value for key, value in out.items() if key not in ("results", "total", "cql", "jql")}
    if merged is None:
        return refusal(
            REASON_NOT_CONFIGURED_FOR_SCOPE if len(summary) == len(plan.skipped) else "search_failed", tool,
            "No connection of this Workspace could run the search.", connections=summary,
        )
    return {**merged, "total": len(results), "results": results, "connections": summary}


async def routed_execute(tool_name: str, params: dict, context: Any, execute: Execute) -> Any:
    from ..content_security.knowledge_fence import unfenced_result

    params = unfenced_result(params)
    base = getattr(context, "project_config", None)
    plan = plan_route(tool_name, params, base,
                      agent_tool=not getattr(context, "workflow_platform_action", False))
    if isinstance(params, dict) and CONNECTION_PARAM in params and plan.descriptor is not None:
        params = {key: value for key, value in params.items() if key != CONNECTION_PARAM}
    if plan.refusal is not None:
        logger.warning("Connector call refused: tool=%s code=%s", tool_name, plan.refusal.get("code"))
        return plan.refusal
    if plan.passthrough:
        out = await execute(params, context)
        if plan.descriptor is not None:
            await note_tool_result(getattr(context, "db", None), routes_of(base), plan.descriptor.connector, None, out)
        return out
    routes = routes_of(base)
    if plan.fan_out:
        return await _fan_out(plan, routes, base, tool_name, params, context, execute)
    connection = plan.targets[0]
    if plan.keys or connection is not None:
        logger.info(
            "Connector call routed: tool=%s connection=%s id=%s",
            tool_name, connection_name(connection), connection_ref(connection),
        )
    return await _run_on(plan, routes, base, connection, tool_name, params, context, execute)


__all__ = [
    "routed_execute",
    "scope_keys",
]
