"""What a connection's grant allows, enforced on the route plan and on tool visibility."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .contract import DEFAULT_CONNECTION_NAME
from .descriptors import descriptor_for_tool
from .grants import LEVEL_OFF, LEVEL_READ
from .resolver import connection_config
from .routes_model import REASON_CONNECTION_DISABLED, NamedConnectionRoutes, ResolvedNamedConnection, routes_of

REASON_AGENT_TOOLS_OFF = "connection_agent_tools_off"
REASON_AGENT_TOOLS_READ_ONLY = "connection_agent_tools_read_only"
STATE_NEEDS_CONFIGURATION = "needs_configuration"
READ_RISK = "read"

MESSAGES = {
    REASON_CONNECTION_DISABLED: "The connection is disabled; nothing ran.",
    REASON_AGENT_TOOLS_OFF: "Agent tools are off for this connection; nothing ran.",
    REASON_AGENT_TOOLS_READ_ONLY: "Agent tools may only read with this connection; this tool writes, nothing ran.",
}


def is_write_tool(tool_name: str) -> bool:
    from ...tools.definitions import get_tool_definition_metadata

    return str(get_tool_definition_metadata(tool_name).risk or "").strip().lower() != READ_RISK


def use_refusal(routes: NamedConnectionRoutes, tool: str, target: ResolvedNamedConnection | None) -> str | None:
    return REASON_CONNECTION_DISABLED if target is not None and not target.is_active else None


def target_level(routes: NamedConnectionRoutes, tool: str, target: ResolvedNamedConnection | None) -> str | None:
    if target is not None:
        return target.level
    default = routes.default_of(tool)
    return default.level if default is not None else None


def level_refusal(level: str | None, tool_name: str) -> str | None:
    if level is None or not tool_name:
        return None
    if level == LEVEL_OFF:
        return REASON_AGENT_TOOLS_OFF
    if level == LEVEL_READ and is_write_tool(tool_name):
        return REASON_AGENT_TOOLS_READ_ONLY
    return None


def target_refusal(routes: NamedConnectionRoutes, tool: str, target: ResolvedNamedConnection | None,
                   tool_name: str = "") -> str | None:
    return use_refusal(routes, tool, target) or level_refusal(target_level(routes, tool, target), tool_name)


def _label(routes: NamedConnectionRoutes, tool: str, target: ResolvedNamedConnection | None) -> dict[str, str]:
    if target is not None:
        return {"connection": target.name, "connection_id": target.id}
    default = routes.default_of(tool)
    if default is not None:
        return {"connection": default.name, "connection_id": default.id}
    return {"connection": DEFAULT_CONNECTION_NAME, "connection_id": DEFAULT_CONNECTION_NAME}


def refusal_of(code: str, routes: NamedConnectionRoutes, tool: str,
               target: ResolvedNamedConnection | None) -> dict[str, Any]:
    return {"error": MESSAGES.get(code, "The connection cannot be used; nothing ran."), "code": code,
            "connector": tool, "state": STATE_NEEDS_CONFIGURATION, **_label(routes, tool, target)}


def gate_plan(plan: Any, base: dict | None, tool_name: str = "") -> Any:
    if plan.refusal is not None or plan.descriptor is None:
        return plan
    routes, tool = routes_of(base), plan.descriptor.connector
    targets = (None,) if plan.passthrough else tuple(plan.targets)
    refused = [(target, target_refusal(routes, tool, target, tool_name)) for target in targets]
    if plan.fan_out:
        kept = tuple(target for target, code in refused if code is None)
        skipped = tuple({**_label(routes, tool, target), "skipped": code} for target, code in refused if code)
        if kept or not refused:
            return replace(plan, targets=kept, skipped=skipped) if skipped else plan
    target, code = next(((target, code) for target, code in refused if code), (None, None))
    if code is None:
        return plan
    return replace(plan, targets=(), passthrough=False, fan_out=False, refusal=refusal_of(code, routes, tool, target))


def hidden_reason(tool_name: str, config: dict | None) -> str | None:
    descriptor = descriptor_for_tool(tool_name)
    routes = routes_of(config)
    if descriptor is None or routes.unavailable:
        return None
    tool = descriptor.connector
    named = routes.of(tool)
    default = routes.default_of(tool)
    if not named and default is None:
        return None
    candidates: list[ResolvedNamedConnection | None] = [*named]
    if default is not None or descriptor.usable(connection_config(dict(config or {}), tool, routes, None)):
        candidates.append(None)
    codes = [target_refusal(routes, tool, target, tool_name) for target in candidates]
    if all(codes):
        return next((code for code in codes if code in (REASON_AGENT_TOOLS_OFF, REASON_AGENT_TOOLS_READ_ONLY)),
                    codes[0])
    return None


__all__ = [
    "REASON_AGENT_TOOLS_OFF",
    "REASON_AGENT_TOOLS_READ_ONLY",
    "STATE_NEEDS_CONFIGURATION",
    "gate_plan",
    "hidden_reason",
    "is_write_tool",
    "level_refusal",
    "refusal_of",
    "target_refusal",
    "use_refusal",
]
