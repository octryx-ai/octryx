"""The closed run capability classes and their deterministic projections."""

from __future__ import annotations

from typing import Any

from ...tools.capability_requirements import CAPABILITY_CHANGE, CAPABILITY_DELIVER, CAPABILITY_READ_ONLY

CAPABILITY_CLASSES: tuple[str, ...] = (CAPABILITY_READ_ONLY, CAPABILITY_CHANGE, CAPABILITY_DELIVER)
_CAPABILITY_RANK = {name: index for index, name in enumerate(CAPABILITY_CLASSES)}

# Agent mode a workflow run uses for its prompt persona and tool surface.
_WORKFLOW_RUN_AGENT_MODE = {
    CAPABILITY_READ_ONLY: "diagnosis",
    CAPABILITY_CHANGE: "coding",
    CAPABILITY_DELIVER: "coding",
}
# Agent-mode capability types that fit inside each class.
_COMPATIBLE_MODE_CAPABILITIES = {
    CAPABILITY_READ_ONLY: frozenset({"diagnosis", "plan"}),
    CAPABILITY_CHANGE: frozenset({"change"}),
    CAPABILITY_DELIVER: frozenset({"change"}),
}

# Key of the frozen run capability state on ``ToolContext.run_capability``.
RUN_CAPABILITY_CLASS_KEY = "class"


def normalize_capability_class(value: Any) -> str | None:
    """Return the class for an exact closed value, otherwise ``None`` (no coercion)."""
    candidate = value.strip() if isinstance(value, str) else ""
    return candidate if candidate in _CAPABILITY_RANK else None


def capability_covers(run_class: str, required_class: str) -> bool:
    run_rank = _CAPABILITY_RANK.get(run_class)
    required_rank = _CAPABILITY_RANK.get(required_class)
    return run_rank is not None and required_rank is not None and required_rank <= run_rank


def guardrail_capability_type(capability_class: str) -> str:
    """The security-analyzer profile for a class: diagnosis rules only for ``read_only``."""
    return "diagnosis" if capability_class == CAPABILITY_READ_ONLY else "change"


def run_agent_mode(
    capability_class: str,
    *,
    workflow_run: bool,
    requested_mode_key: str,
    requested_mode_capability: str,
) -> str:
    default_mode = _WORKFLOW_RUN_AGENT_MODE[capability_class]
    if workflow_run or not requested_mode_key:
        return default_mode
    if requested_mode_capability in _COMPATIBLE_MODE_CAPABILITIES[capability_class]:
        return requested_mode_key
    return default_mode


def run_capability_state(context: Any) -> dict[str, Any] | None:
    state = getattr(context, "run_capability", None)
    return state if isinstance(state, dict) else None


def enforced_run_capability_class(context: Any) -> str | None:
    """The enforced class of the run behind ``context``; ``None`` for an unenforced run."""
    state = run_capability_state(context)
    if state is None or state.get("enforced") is not True:
        return None
    return normalize_capability_class(state.get(RUN_CAPABILITY_CLASS_KEY))


__all__ = [
    "CAPABILITY_CLASSES",
    "RUN_CAPABILITY_CLASS_KEY",
    "capability_covers",
    "enforced_run_capability_class",
    "guardrail_capability_type",
    "normalize_capability_class",
    "run_agent_mode",
    "run_capability_state",
]
