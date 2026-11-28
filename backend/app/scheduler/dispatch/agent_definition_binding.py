"""Explicit AgentDefinition dispatch binding of an Action."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ...models.project.task import (
    AGENT_DEFINITION_BINDING,
    DISPATCH_BINDINGS,
    TASK_DEFINITION_BINDING,
    WORKFLOW_RUN_BINDING,
)
from ..execution.action_admission import ActionAdmissionError

BOUND_TASK_TYPE = "agent_run"

BINDING_INVALID = "dispatch_binding_invalid"
BINDING_TYPE_UNSUPPORTED = "dispatch_binding_type_unsupported"
BINDING_STEPS_ENABLED = "dispatch_binding_steps_enabled"
BINDING_AGENT_REQUIRED = "dispatch_binding_agent_required"

BINDING_MESSAGES = {
    BINDING_INVALID: "The Action's dispatch binding is not a supported value.",
    BINDING_TYPE_UNSUPPORTED: "An agent-bound Action must be an agent run.",
    BINDING_STEPS_ENABLED: "An agent-bound Action cannot have enabled steps.",
    BINDING_AGENT_REQUIRED: "An agent-bound Action must select an agent.",
}


class DispatchBindingError(ActionAdmissionError):
    def as_metadata(self) -> dict[str, str]:
        return {"code": self.code, "message": BINDING_MESSAGES[self.code]}


def is_agent_definition_bound(task: Any) -> bool:
    return getattr(task, "dispatch_binding", None) == AGENT_DEFINITION_BINDING


def binding_defect(*, task_type: Any, config: Any, has_enabled_steps: bool) -> str | None:
    if task_type != BOUND_TASK_TYPE:
        return BINDING_TYPE_UNSUPPORTED
    if has_enabled_steps:
        return BINDING_STEPS_ENABLED
    agent_definition_id = config.get("agent_definition_id") if isinstance(config, dict) else None
    if not isinstance(agent_definition_id, str) or not agent_definition_id.strip():
        return BINDING_AGENT_REQUIRED
    return None


async def has_enabled_steps(db: Any, task_id: str) -> bool:
    from ...models import TaskStep

    row = await db.execute(
        select(TaskStep.id).where(TaskStep.task_id == task_id, TaskStep.is_enabled.is_(True)).limit(1)
    )
    return row.first() is not None


async def require_bound_task_runnable(db: Any, task: Any) -> None:
    binding = getattr(task, "dispatch_binding", None)
    if binding not in DISPATCH_BINDINGS:
        raise DispatchBindingError(BINDING_INVALID)
    if binding == TASK_DEFINITION_BINDING:
        return
    if binding == WORKFLOW_RUN_BINDING:
        from .workflow_run_binding import require_workflow_bound_state

        await require_workflow_bound_state(db, task, has_steps=await has_enabled_steps(db, task.id))
        return
    defect = binding_defect(
        task_type=task.task_type, config=task.config, has_enabled_steps=await has_enabled_steps(db, task.id)
    )
    if defect is not None:
        raise DispatchBindingError(defect)


__all__ = [
    "BINDING_AGENT_REQUIRED",
    "BINDING_INVALID",
    "BINDING_STEPS_ENABLED",
    "BINDING_TYPE_UNSUPPORTED",
    "DispatchBindingError",
    "binding_defect",
    "has_enabled_steps",
    "is_agent_definition_bound",
    "require_bound_task_runnable",
]
