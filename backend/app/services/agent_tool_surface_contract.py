"""Values, key mapping and step rules of an Agent Definition's tool surface: ``governed`` (the default)
takes its tools from ``turn_tool_surface``, ``none`` is a text-only deny boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

TOOL_SURFACE_GOVERNED = "governed"
# A deny boundary: no tool definitions, dispatch refuses every call, and a turn that would need
# tools (selected workflow, steps with tools) stops as needs_configuration before any model call.
TOOL_SURFACE_NONE = "none"
TOOL_SURFACES = (TOOL_SURFACE_GOVERNED, TOOL_SURFACE_NONE)
DEFAULT_TOOL_SURFACE = TOOL_SURFACE_GOVERNED

# Column, snapshot, export package and write body use the field; runtime and panel read payloads the key.
TOOL_SURFACE_FIELD = "tool_surface"
TOOL_SURFACE_PAYLOAD_KEY = "toolSurface"

DECISION_SOURCE = "agent_tool_surface"
REQUIREMENT_METADATA_KEY = "agent_tool_surface"
REASON_CODE_INVALID = "agent_tool_surface_invalid"
REASON_CODE_WORKFLOW_CONFLICT = "agent_tool_surface_workflow_conflict"
REASON_CODE_STEP_CONFLICT = "agent_tool_surface_step_conflict"
REFUSAL_POLICY = "agent_tool_surface"
REASON_CODE_TEXT_ONLY = "agent_tool_surface_none"

_TOOL_USE_REQUIRED = "required"
_TOOL_USE_OPTIONAL = "optional"


class ToolSurfaceConflictError(ValueError):
    pass


# A present value is never coerced: null, "" or " none" are refused, not read as governed.
def normalize_tool_surface(value: Any) -> str:
    if not isinstance(value, str) or value not in TOOL_SURFACES:
        raise ValueError("tool_surface must be 'governed' or 'none'")
    return value


# Only a missing key means governed; a present one is validated as is.
def declared_tool_surface(source: Mapping[str, Any], *keys: str) -> str:
    for key in keys or (TOOL_SURFACE_FIELD,):
        if key in source:
            return normalize_tool_surface(source[key])
    return DEFAULT_TOOL_SURFACE


def snapshot_tool_surface(header: Mapping[str, Any]) -> Any:
    return header[TOOL_SURFACE_FIELD] if TOOL_SURFACE_FIELD in header else DEFAULT_TOOL_SURFACE


# The column is NOT NULL with default governed; None exists only on an unflushed object.
def live_row_tool_surface(value: Any) -> Any:
    return DEFAULT_TOOL_SURFACE if value is None else value


# A present non-enum value passes through as a marker so denies_tools fails closed on it.
def payload_tool_surface(agent_definition: Mapping[str, Any] | None) -> str:
    if not isinstance(agent_definition, Mapping) or TOOL_SURFACE_PAYLOAD_KEY not in agent_definition:
        return DEFAULT_TOOL_SURFACE
    value = agent_definition.get(TOOL_SURFACE_PAYLOAD_KEY)
    return value if isinstance(value, str) else repr(value)


def denies_tools(agent_definition: Mapping[str, Any] | None) -> bool:
    return payload_tool_surface(agent_definition) != TOOL_SURFACE_GOVERNED


# Omitting governed keeps a governed revision's checksum independent of the field; any other
# value, "" included, is written verbatim so publication validation and import refuse it.
def snapshot_tool_surface_entry(tool_surface: Any) -> dict[str, Any]:
    value = live_row_tool_surface(tool_surface)
    return {} if value == TOOL_SURFACE_GOVERNED else {TOOL_SURFACE_FIELD: value}


def _field(step: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in step:
            return step[key]
    return None


def step_needs_tools(step: Mapping[str, Any]) -> bool:
    if not _field(step, "isEnabled", "is_enabled"):
        return False
    if any(str(tool or "").strip() for tool in (_field(step, "allowedTools", "allowed_tools") or [])):
        return True
    config = _field(step, "stepConfig", "step_config")
    raw = config.get("tool_use") if isinstance(config, Mapping) else None
    # An unrecognised tool_use counts as required, exactly like the step guard.
    return raw is not None and str(raw).strip().lower() != _TOOL_USE_OPTIONAL


def tool_surface_step_conflict(tool_surface: str, steps: Iterable[Mapping[str, Any]]) -> str | None:
    if tool_surface != TOOL_SURFACE_NONE:
        return None
    names = [str(_field(step, "name") or "unnamed step") for step in steps if step_needs_tools(step)]
    if not names:
        return None
    return (
        "No tools (text only) conflicts with steps that use tools: "
        f"{', '.join(names)}. Remove their allowed tools and required tool use, "
        "or keep the policy-governed tools setting."
    )


def ensure_no_step_conflict(tool_surface: str, steps: Iterable[Mapping[str, Any]]) -> None:
    message = tool_surface_step_conflict(tool_surface, steps)
    if message:
        raise ToolSurfaceConflictError(message)


def step_row_view(step: Any) -> dict[str, Any]:
    return {
        "name": step.name,
        "is_enabled": bool(step.is_enabled),
        "allowed_tools": list(step.allowed_tools or []),
        "step_config": step.step_config or {},
    }
