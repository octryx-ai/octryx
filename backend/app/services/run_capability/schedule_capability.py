"""The capability class a schedule (a scheduler ``Task``) declares.

A scheduled run never picks a workflow; the task declares its class as data
(``Task.config.capability_class``). Everything the task runs dispatches under it:

- its agent runs (``run_agent``), through the ``declared_run_capability`` session metadata the
  scheduler sets on every session it creates or reuses, including spawned per-item sub-sessions;
- its connector steps, through the tool context.

A task that declares nothing runs ``read_only``. The declaration is validated when the task or
one of its steps is saved: an unsupported value is refused, and so is a step whose connector
action or allowed tools need more than the declared class.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException

from .declared import (
    DECLARED_CAPABILITY_KEY,
    DECLARED_RUN_CAPABILITY_METADATA_KEY,
    SOURCE_SCHEDULE_DEFINITION,
    DeclaredRunCapability,
    declared_run_capability,
    validate_declared_capability_class,
)


def _config(config: Any) -> dict[str, Any]:
    return config if isinstance(config, dict) else {}


def schedule_declared_capability(task: Any) -> DeclaredRunCapability:
    """The class the task's config declares; a task that declares nothing runs ``read_only``."""
    return declared_run_capability(
        _config(getattr(task, "config", None)).get(DECLARED_CAPABILITY_KEY), source=SOURCE_SCHEDULE_DEFINITION
    )


def schedule_session_capability_metadata(task: Any) -> dict[str, Any]:
    """The session metadata that makes the task's agent runs resolve the declared class."""
    return {DECLARED_RUN_CAPABILITY_METADATA_KEY: schedule_declared_capability(task).to_metadata()}


def schedule_tool_context_capability(task: Any) -> dict[str, Any]:
    """The ``ToolContext.run_capability`` state of the task's direct tool calls."""
    return schedule_declared_capability(task).tool_context_state()


def schedule_step_tool_names(steps: Iterable[Any]) -> list[str]:
    """The tools the task's steps name: connector actions and allowed tools."""
    names: list[str] = []
    for step in steps:
        action = str(getattr(step, "connector_action", None) or "").strip()
        if action:
            names.append(action)
        names.extend(str(item).strip() for item in getattr(step, "allowed_tools", None) or [] if str(item).strip())
    return sorted(set(names))


def require_valid_schedule_capability(config: Any, steps: Iterable[Any] = ()) -> None:
    """Refuse (422) a task config whose declared class is unsupported or below its steps' tools."""
    errors = validate_declared_capability_class(
        _config(config).get(DECLARED_CAPABILITY_KEY), tool_names=schedule_step_tool_names(steps), subject="Task"
    )
    if errors:
        raise HTTPException(status_code=422, detail={"valid": False, "errors": errors})


__all__ = [
    "require_valid_schedule_capability",
    "schedule_declared_capability",
    "schedule_session_capability_metadata",
    "schedule_step_tool_names",
    "schedule_tool_context_capability",
]
