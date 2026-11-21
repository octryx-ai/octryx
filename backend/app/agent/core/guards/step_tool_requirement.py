"""Explicit tool-use requirement of an agent step.

A step's ``allowed_tools`` is an allowlist: it limits which tools the step may
call. Whether the step must call one of them before it may complete is a
separate decision, stated in the step configuration as ``tool_use``:

``required``
    The step completes only after a tool call; a text-only reply gets one
    reminder, and a second text-only reply on the final step ends the run with
    an explicit stop that names the step and its tools.
``optional``
    The step may complete with a text answer (the allowlist still applies to
    any tool it does call).

Without the key a step's tool use is optional (``default``): an allowlist alone
never makes a tool call mandatory. An unrecognised value fails closed to
``required`` (``invalid_explicit``) so a typo never relaxes a step.
"""

from __future__ import annotations

from typing import Any

from .response_guards import get_step_allowed_tools, get_step_field
from .stop_text import agent_stop_text

STEP_TOOL_USE_KEY = "tool_use"
TOOL_USE_REQUIRED = "required"
TOOL_USE_OPTIONAL = "optional"

SOURCE_EXPLICIT = "explicit"
SOURCE_DEFAULT = "default"
SOURCE_INVALID_EXPLICIT = "invalid_explicit"

# Text-only replies on a step whose tool use is required before the run stops on
# the final step: the first gets the reminder, the second shows the model will
# not call a tool for this request, so repeating the same context is pointless.
TOOL_REQUIREMENT_DECLINE_LIMIT = 2


def step_tool_use(step: dict[str, Any] | None) -> tuple[bool, str]:
    """Return ``(required, source)`` for *step*."""
    if not step:
        return False, SOURCE_DEFAULT
    config = get_step_field(step, "stepConfig", "step_config", None)
    raw = config.get(STEP_TOOL_USE_KEY) if isinstance(config, dict) else None
    if raw is not None:
        value = str(raw).strip().lower()
        if value == TOOL_USE_REQUIRED:
            return True, SOURCE_EXPLICIT
        if value == TOOL_USE_OPTIONAL:
            return False, SOURCE_EXPLICIT
        return True, SOURCE_INVALID_EXPLICIT
    return False, SOURCE_DEFAULT


def step_requires_tool_use(step: dict[str, Any] | None) -> bool:
    return step_tool_use(step)[0]


def tool_requirement_declined(attempts_used: int) -> bool:
    return attempts_used >= TOOL_REQUIREMENT_DECLINE_LIMIT


def build_tool_required_stop(step: dict[str, Any] | None) -> str:
    step_name = str((step or {}).get("name") or "").strip() or "current step"
    tools = get_step_allowed_tools(step)
    tool_names = ", ".join(tools) if tools else "any available tool"
    return agent_stop_text("guard.step.tool_required_stop", step_name=step_name, tool_names=tool_names)


__all__ = [
    "STEP_TOOL_USE_KEY",
    "TOOL_REQUIREMENT_DECLINE_LIMIT",
    "TOOL_USE_OPTIONAL",
    "TOOL_USE_REQUIRED",
    "build_tool_required_stop",
    "step_requires_tool_use",
    "step_tool_use",
    "tool_requirement_declined",
]
