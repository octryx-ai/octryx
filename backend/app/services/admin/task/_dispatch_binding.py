"""Save-time validation of explicit agent or workflow Action dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.task import DISPATCH_BINDINGS, TASK_DEFINITION_BINDING, WORKFLOW_RUN_BINDING
from ...agent_definition_execution_outcomes import AgentDefinitionExecutionError

FIELD = "dispatch_binding"


def _binding():
    # The scheduler package imports the admin task service at import time; resolve lazily.
    from ....scheduler.dispatch import agent_definition_binding

    return agent_definition_binding


def _refuse(code: str, message: str, **typed: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": message, "code": code, "field": FIELD, **typed})


def require_binding_value(value: Any) -> str:
    binding = _binding()
    if isinstance(value, str) and value in DISPATCH_BINDINGS:
        return value
    raise _refuse(binding.BINDING_INVALID, binding.BINDING_MESSAGES[binding.BINDING_INVALID])


async def require_bound_state(
    db: AsyncSession,
    *,
    binding: str,
    task_type: Any,
    config: Any,
    owner_id: str,
    project_id: str | None,
    has_enabled_steps: bool,
) -> None:
    if binding == TASK_DEFINITION_BINDING:
        return
    from ....scheduler.execution.action_admission import ActionAdmissionError, admit_agent_turn

    rules = _binding()
    if binding == WORKFLOW_RUN_BINDING:
        from ....scheduler.dispatch.workflow_run_binding import require_workflow_bound_state

        effective = SimpleNamespace(task_type=task_type, config=config, owner_id=owner_id, project_id=project_id)
        try:
            await require_workflow_bound_state(db, effective, has_steps=has_enabled_steps)
        except ActionAdmissionError as exc:
            refusal = exc.as_metadata()
            raise _refuse(refusal.pop("code"), refusal.pop("message"), **refusal) from None
        return
    defect = rules.binding_defect(task_type=task_type, config=config, has_enabled_steps=has_enabled_steps)
    if defect is not None:
        raise _refuse(defect, rules.BINDING_MESSAGES[defect])
    effective = SimpleNamespace(task_type=task_type, config=config, owner_id=owner_id, project_id=project_id)
    try:
        await admit_agent_turn(db, effective)
    except ActionAdmissionError as exc:
        raise _refuse(exc.code, exc.as_metadata()["message"]) from None
    except AgentDefinitionExecutionError as exc:
        raise _refuse(exc.code, "The selected agent cannot run in this state.") from None


def require_step_allowed(*, binding: str | None, enabled: bool) -> None:
    if binding != TASK_DEFINITION_BINDING and enabled:
        rules = _binding()
        raise _refuse(rules.BINDING_STEPS_ENABLED, rules.BINDING_MESSAGES[rules.BINDING_STEPS_ENABLED])


__all__ = ["require_binding_value", "require_bound_state", "require_step_allowed"]
