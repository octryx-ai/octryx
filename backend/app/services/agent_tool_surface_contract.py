"""Values, key mapping and step rules of an agent's tool surface.

The contract is described in :mod:`app.services.agent_tool_surface`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

TOOL_SURFACE_GOVERNED = "governed"
TOOL_SURFACE_NONE = "none"
TOOL_SURFACES = (TOOL_SURFACE_GOVERNED, TOOL_SURFACE_NONE)
DEFAULT_TOOL_SURFACE = TOOL_SURFACE_GOVERNED

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
    """``none`` was combined with steps that need tools; the message is plain English."""


def normalize_tool_surface(value: Any) -> str:
    """*value* when it is exactly one of the enum values; anything else (``None``, ``""`` ...) raises ``ValueError``."""
    if not isinstance(value, str) or value not in TOOL_SURFACES:
        raise ValueError("tool_surface must be 'governed' or 'none'")
    return value


def declared_tool_surface(source: Mapping[str, Any], *keys: str) -> str:
    """The surface a write body, package or snapshot header declares.

    The default applies only when none of *keys* is present. A present value is
    validated as is, so an explicit ``null`` or ``""`` raises ``ValueError``.
    """
    for key in keys or (TOOL_SURFACE_FIELD,):
        if key in source:
            return normalize_tool_surface(source[key])
    return DEFAULT_TOOL_SURFACE


def snapshot_tool_surface(header: Mapping[str, Any]) -> Any:
    """The runtime payload value of a snapshot header: missing means ``governed``, present is verbatim."""
    return header[TOOL_SURFACE_FIELD] if TOOL_SURFACE_FIELD in header else DEFAULT_TOOL_SURFACE


def live_row_tool_surface(value: Any) -> Any:
    """The runtime payload value of a live row's column, verbatim. ``None`` only on an unflushed object."""
    return DEFAULT_TOOL_SURFACE if value is None else value


def payload_tool_surface(agent_definition: Mapping[str, Any] | None) -> str:
    """The declared surface of a runtime payload.

    No agent or a missing key means ``governed``. Any present value that is not exactly an enum
    value is returned as a non-enum marker (``repr`` for non-strings), so callers fail closed on it
    (see :func:`denies_tools`).
    """
    if not isinstance(agent_definition, Mapping) or TOOL_SURFACE_PAYLOAD_KEY not in agent_definition:
        return DEFAULT_TOOL_SURFACE
    value = agent_definition.get(TOOL_SURFACE_PAYLOAD_KEY)
    return value if isinstance(value, str) else repr(value)


def denies_tools(agent_definition: Mapping[str, Any] | None) -> bool:
    """True unless the payload explicitly or implicitly declares ``governed`` (unknown values deny)."""
    return payload_tool_surface(agent_definition) != TOOL_SURFACE_GOVERNED


def snapshot_tool_surface_entry(tool_surface: Any) -> dict[str, Any]:
    """The snapshot/export key for a live row's value.

    It is omitted for ``governed``, including an unflushed row whose column default has yet to apply.
    Every other value, including ``""``, is written verbatim and refused by publication validation
    and import.
    """
    value = live_row_tool_surface(tool_surface)
    return {} if value == TOOL_SURFACE_GOVERNED else {TOOL_SURFACE_FIELD: value}


def _field(step: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in step:
            return step[key]
    return None


def step_needs_tools(step: Mapping[str, Any]) -> bool:
    """An enabled step that declares tools or explicitly requires tool use (any spelling of the keys).

    An unrecognised ``tool_use`` value counts as ``required``, exactly like the step guard.
    """
    if not _field(step, "isEnabled", "is_enabled"):
        return False
    if any(str(tool or "").strip() for tool in (_field(step, "allowedTools", "allowed_tools") or [])):
        return True
    config = _field(step, "stepConfig", "step_config")
    raw = config.get("tool_use") if isinstance(config, Mapping) else None
    return raw is not None and str(raw).strip().lower() != _TOOL_USE_OPTIONAL


def tool_surface_step_conflict(tool_surface: str, steps: Iterable[Mapping[str, Any]]) -> str | None:
    """A plain-English refusal when ``none`` meets steps that need tools, else ``None``."""
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
    """The fields of an ``AgentStep`` row the conflict rule reads."""
    return {
        "name": step.name,
        "is_enabled": bool(step.is_enabled),
        "allowed_tools": list(step.allowed_tools or []),
        "step_config": step.step_config or {},
    }
