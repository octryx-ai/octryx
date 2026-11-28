"""What the approval card of a gated tool call shows: the connection, the tool's own preview, every field."""

from __future__ import annotations

import json
from typing import Any

from app.services.approval.tool_texts import readable_title

from ...tools.context import ToolContext
from ...tools.definitions import get_tool_definition_metadata
from ..change_preview import build_tool_change_preview


def _outbound_message_details(payload: dict[str, Any] | None) -> list[str]:
    # Shown in full, never shortened: the contract refused anything over its limits before this point.
    values = payload if isinstance(payload, dict) else {}
    return [
        f"recipient: {values.get('reporter_email') or ''}",
        f"ticket: {values.get('ticket_id') or ''}",
        f"message: {values.get('question') or ''}",
    ]


def _connection_label(tool_name: str, params: dict[str, Any], project_config: Any) -> str:
    from ..named_connections.route_planner import plan_route
    from ..named_connections.routes_model import routes_of

    try:
        plan = plan_route(tool_name, params, project_config if isinstance(project_config, dict) else {})
    except Exception:  # noqa: BLE001 - the label is informative; dispatch routes (and refuses) the call itself
        return ""
    if plan.refusal is not None or plan.descriptor is None:
        return ""
    routes = routes_of(project_config if isinstance(project_config, dict) else {})
    default = routes.default_of(plan.descriptor.connector)
    names = [target.name if target is not None else (default.name if default is not None else "default")
             for target in (plan.targets or (None,))]
    return ", ".join(dict.fromkeys(names))


def _field_lines(params: dict[str, Any]) -> list[str]:
    # No shortening: the person confirms exactly what is written.
    lines = []
    for key, value in (params or {}).items():
        if value in (None, "", [], {}):
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        lines.append(f"{key}: {text}")
    return lines


async def _routed_tool_preview(tool_name: str, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    # Read on the connection the call runs on: the merged config could name another Jira.
    from ..named_connections.tool_routing import routed_execute

    async def preview(routed_params: dict[str, Any], routed_context: Any) -> dict[str, Any]:
        return await build_tool_change_preview(tool_name, routed_params, routed_context) or {}

    own = await routed_execute(tool_name, params, context, preview)
    return own if isinstance(own, dict) and "error" not in own else {}


def chat_write_route_refusal(tool_name: str, params: dict[str, Any], project_config: Any) -> dict[str, Any] | None:
    # Refused before the person confirms a call that would fail; the refusal names the serving connection.
    from ..named_connections.route_plan import CONNECTION_PARAM
    from ..named_connections.route_planner import plan_route

    config = project_config if isinstance(project_config, dict) else {}
    try:
        plan = plan_route(tool_name, params, config)
    except Exception:  # noqa: BLE001 - dispatch plans (and refuses) the call itself
        return None
    if plan.refusal is None:
        return None
    result = dict(plan.refusal)
    if CONNECTION_PARAM in (params or {}):
        unnamed = {key: value for key, value in params.items() if key != CONNECTION_PARAM}
        try:
            fallback = plan_route(tool_name, unnamed, config)
        except Exception:  # noqa: BLE001 - the hint is optional
            fallback = None
        if fallback is not None and fallback.refusal is None:
            label = _connection_label(tool_name, unnamed, config)
            result["hint"] = (f"Leave out '{CONNECTION_PARAM}' (or pass '{label}'): the requested scope is served by "
                              f"the connection '{label}'.")
    return result


async def _chat_write_preview(tool_name: str, params: dict[str, Any], context: ToolContext,
                              base: dict[str, Any]) -> dict[str, Any]:
    # The person confirms the exact fields, not only the tool name.
    metadata = get_tool_definition_metadata(tool_name)
    connection = _connection_label(tool_name, params, context.project_config)
    own: dict[str, Any] = {}
    try:
        own = await _routed_tool_preview(tool_name, params, context)
    except Exception:  # noqa: BLE001 - a tool's preview is optional; the field list below still shows the call
        own = {}
    # A custom REST write names its own connection (its rows are not named connections, ``rest_connector/preview``).
    connection = connection or str(own.get("connection") or "")
    details = [f"tool: {tool_name}"]
    if metadata.connector:
        details.append(f"connector: {metadata.connector}")
    if connection:
        details.append(f"connection: {connection}")
    details.extend(str(item) for item in own.get("details") or []
                   if str(item or "").strip() and not str(item).startswith("connection: "))
    if not own.get("fields_shown"):
        details.extend(_field_lines(params))
    details.extend(str(item) for item in base.get("details") or [])
    payload = {**base, "details": details}
    for key in ("title", "summary", "before", "after"):
        if own.get(key):
            payload[key] = own[key]
    # A write plan entry comes without the gate's title: the tool in words, never its name or "Execute tool x".
    payload["title"] = readable_title(payload.get("title"), tool_name)
    payload["kind"] = "tool_execution"
    payload["connection"] = connection or None
    return payload


async def _rest_write_preview(tool_name: str, params: dict[str, Any], context: ToolContext,
                              base: dict[str, Any]) -> dict[str, Any]:
    own = await build_tool_change_preview(tool_name, params, context) or {}
    payload = {**base, "details": [*(base.get("details") or []), *(own.get("details") or [])]}
    for key in ("title", "summary", "connection", "url", "method", "header_names", "body"):
        if own.get(key) is not None:
            payload[key] = own[key]
    return payload
