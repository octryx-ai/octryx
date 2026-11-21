"""The capability a sub-agent run is bounded by: the spawning turn's class.

A sub-agent never picks a workflow and never declares anything of its own. Its profile is derived
from the turn that spawned it, tightening only:

- the spawning tool records the parent turn's *enforced* class, frozen on its ``ToolContext``, as
  the child session's ``declared_run_capability`` (``source: sub_agent_parent``);
- at run time, :mod:`.resolution` takes the parent session's recorded class first and caps every
  other outcome (a workflow, an escalation) at it, so a child never exceeds its parent;
- a spawning turn without an enforced class cannot bound a child: the declaration is invalid and
  the child's turn is ``needs_configuration``. Nothing is inferred from the task text.
"""

from __future__ import annotations

from typing import Any

from .classes import enforced_run_capability_class
from .declared import DECLARED_RUN_CAPABILITY_METADATA_KEY, SOURCE_SUB_AGENT_PARENT, DeclaredRunCapability

_UNBOUNDED_PARENT_ERROR = "The spawning run has no enforced run capability, so a sub-agent cannot be bounded by it."


def sub_agent_declared_capability(parent_context: Any) -> DeclaredRunCapability:
    """The class a child inherits from the spawning turn's frozen run capability."""
    parent_class = enforced_run_capability_class(parent_context)
    if parent_class is None:
        return DeclaredRunCapability(
            capability_class=None, source=SOURCE_SUB_AGENT_PARENT, error=_UNBOUNDED_PARENT_ERROR
        )
    return DeclaredRunCapability(capability_class=parent_class, source=SOURCE_SUB_AGENT_PARENT)


def sub_agent_session_capability_metadata(parent_context: Any) -> dict[str, Any]:
    """The child session metadata that makes the child's turns resolve the parent's class."""
    return {DECLARED_RUN_CAPABILITY_METADATA_KEY: sub_agent_declared_capability(parent_context).to_metadata()}


__all__ = ["sub_agent_declared_capability", "sub_agent_session_capability_metadata"]
