"""Generic Task Step Executor."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

# These are imported at module level so tests can patch them cleanly.
from ...services.agent_definition_execution_outcomes import (
    AgentDefinitionExecutionError,
)
from ._step_action_summary import _render_action_summary_message
from ._step_agent_kinds import AgentStepKinds
from ._step_agent_loader import load_agent_for_step
from ._step_check_kinds import CheckStepKinds
from ._step_context import (
    build_step_prompt,
    render_template_params,
    render_template_str,
    resolve_field,
)
from ._step_data_kinds import DataStepKinds
from ._step_result import StepResult

if TYPE_CHECKING:
    from ...models.project.task import Task, TaskRun, TaskStep

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class StepExecutor(AgentStepKinds, CheckStepKinds, DataStepKinds):
    """Drives step-by-step execution for a single TaskRun."""

    def __init__(self, scheduler: Any) -> None:
        # scheduler exposes _run_agent_for_task, _assign_task_run_session, etc.
        self.scheduler = scheduler

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def execute(self, db: Any, task: Task, task_run: TaskRun) -> dict:
        """Execute all enabled steps in order and return the final context."""
        from sqlalchemy import select

        from ...models.project.task import TaskStep

        result = await db.execute(
            select(TaskStep)
            .where(TaskStep.task_id == task.id, TaskStep.is_enabled.is_(True))
            .order_by(TaskStep.position)
        )
        steps: list[TaskStep] = result.scalars().all()

        if not steps:
            raise ValueError(f"Task {task.id} ({task.name!r}) has no enabled steps configured")

        context: dict[str, Any] = {
            "task_id": task.id,
            "task_name": task.name,
            "task_config": dict(task.config or {}),
            "run_id": task_run.id,
            "steps": {},  # position (str) → StepResult
        }

        position_map: dict[int, TaskStep] = {s.position: s for s in steps}
        steps_log: list[dict] = []
        current_pos: int | None = min(position_map)

        while current_pos is not None:
            step = position_map.get(current_pos)
            if step is None:
                break

            logger.info(
                "[step_executor] task=%s run=%s step=%d (%s) %r",
                task.id,
                task_run.id,
                step.position,
                step.step_type,
                step.name,
            )

            step_result = await self._execute_step(step, context, db, task, task_run)
            context["steps"][str(step.position)] = step_result

            steps_log.append(step_result.to_dict())
            task_run.steps_log = steps_log
            await self._record_action_summary_message(db, task_run, step_result)
            await db.commit()

            if step_result.status == "error":
                logger.warning(
                    "[step_executor] step %d error: %s – continuing pipeline",
                    step.position,
                    step_result.error,
                )

            # Determine next position
            if step.step_type == "condition":
                current_pos = step_result.output.get("next_position")
            else:
                future = [s for s in steps if s.position > current_pos]
                current_pos = min((s.position for s in future), default=None)

        return context

    async def _record_action_summary_message(self, db: Any, task_run: TaskRun, step_result: StepResult) -> None:
        summary = step_result.output.get("action_summary") if isinstance(step_result.output, dict) else None
        if not task_run.session_id or not isinstance(summary, dict):
            return

        from ...models import Message

        content = _render_action_summary_message(summary)
        if not content:
            return
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=task_run.session_id,
                role="assistant",
                content=content,
                model=str(summary.get("primary_model") or "") or None,
                tool_results={
                    "step_id": step_result.step_id,
                    "step_name": step_result.name,
                    "action_summary": summary,
                },
            )
        )

    # ------------------------------------------------------------------
    # Step dispatcher
    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        handlers = {
            "connector_fetch": self._exec_connector_fetch,
            "analysis": self._exec_analysis,
            "sub_agent_spawn": self._exec_sub_agent_spawn,
            "verification": self._exec_verification,
            "output": self._exec_output,
            "condition": self._exec_condition,
        }
        handler = handlers.get(step.step_type, self._exec_analysis)
        try:
            return await handler(step, context, db, task, task_run)
        except AgentDefinitionExecutionError as exc:
            # The step was configured with an agent definition the platform
            # will not execute. It fails with the typed state persisted on the step
            # instead of running as if no agent had been configured.
            logger.error(
                "[step_executor] step %d refused: %s", step.position, exc.code
            )
            return StepResult(
                step_id=step.id,
                position=step.position,
                name=step.name,
                step_type=step.step_type,
                status="error",
                error=exc.code,
                refusal=exc.as_metadata(),
            )
        except Exception as exc:
            logger.exception("[step_executor] step %d crashed", step.position)
            return StepResult(
                step_id=step.id,
                position=step.position,
                name=step.name,
                step_type=step.step_type,
                status="error",
                error=str(exc),
            )


    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------


    def _build_step_prompt(
        self,
        step: TaskStep,
        context: dict,
        item: Any = None,
    ) -> str:
        return build_step_prompt(step, context, StepResult, item=item)


    def _resolve_field(self, ref: str, context: dict) -> Any:
        return resolve_field(ref, context, StepResult)

    def _render_template_params(self, params: dict, context: dict) -> dict:
        return render_template_params(params, context, StepResult)

    def _render_template_str(self, template: str, context: dict) -> str:
        return render_template_str(template, context, StepResult)

    async def _load_agent_for_step(
        self,
        step: TaskStep,
        task: Task,
        db: Any,
    ) -> tuple[dict | None, str | None, str | None]:
        return await load_agent_for_step(step, task, db, logger)
