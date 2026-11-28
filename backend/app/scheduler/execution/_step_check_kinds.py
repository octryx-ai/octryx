"""Task steps that judge: verification by the platform's model and conditions over the run's context."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.error_facts import error_text

# These are imported at module level so tests can patch them cleanly.
from ...services.agent_definition_execution_outcomes import (
    payload_resolution_metadata,
)
from ._step_conditions import evaluate_condition_expression
from ._step_result import StepResult
from ._step_verification import build_verification_prompt, classify_verification_response

if TYPE_CHECKING:
    from ...models.project.task import Task, TaskRun, TaskStep

logger = logging.getLogger(__name__)


class CheckStepKinds:
    async def _exec_verification(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        agent_def, runtime_target_id, thinking_level = await self._load_agent_for_step(step, task, db)
        max_attempts = max(1, step.max_fix_attempts or 2)
        last_session_id: str | None = None
        last_result: dict = {}

        for attempt in range(max_attempts + 1):
            prompt = build_verification_prompt(self._build_step_prompt(step, context), attempt, max_attempts)

            session, result_payload = await self.scheduler._run_agent_for_task(
                db,
                task,
                prompt,
                agent_definition=agent_def,
                runtime_target_id=runtime_target_id,
                thinking_level=thinking_level,
                session_metadata={
                    "title": f"{task.name} · {step.name} · attempt {attempt}",
                    "task_id": task.id,
                    "task_run_id": task_run.id,
                    "step_id": step.id,
                    "trigger": "verification",
                    "fix_attempt": attempt,
                    # Same canonical provenance entry as every other session
                    # this executor opens — one shape, not one per step type.
                    **payload_resolution_metadata(agent_def),
                },
                max_iterations=int((task.config or {}).get("max_iterations") or 32),
                skip_session_reuse=True,
                parent_session_id=task_run.session_id,
            )
            last_session_id = session.id
            last_result = result_payload

            passed, failed = classify_verification_response(result_payload)

            if passed or not failed:
                return StepResult(
                    step_id=step.id,
                    position=step.position,
                    name=step.name,
                    step_type=step.step_type,
                    status="success",
                    output=last_result,
                    fix_attempts=attempt,
                    session_ids=[last_session_id],
                )

            if attempt < max_attempts:
                logger.warning(
                    "[step_executor] verification step %d: attempt %d/%d failed, retrying",
                    step.position,
                    attempt + 1,
                    max_attempts,
                )

        return StepResult(
            step_id=step.id,
            position=step.position,
            name=step.name,
            step_type=step.step_type,
            status="error",
            output=last_result,
            error=f"Verification failed after {max_attempts} attempts",
            fix_attempts=max_attempts,
            session_ids=[last_session_id] if last_session_id else [],
        )
    async def _exec_condition(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        expr = (step.condition_expr or "").strip()
        if not expr:
            return StepResult(
                step_id=step.id,
                position=step.position,
                name=step.name,
                step_type=step.step_type,
                status="error",
                error="condition_expr is empty",
            )
        try:
            result = self._evaluate_condition_expression(expr, context)
        except Exception as exc:
            # Intentional graceful degradation: a bad/unevaluable branch
            # expression falls through to the false branch rather than aborting
            # the pipeline. The failure is logged and the chosen branch is
            # recorded in ``output`` below (next_position / condition_result),
            # so it stays visible on the run trail — not silently swallowed.
            logger.warning("[step_executor] condition eval failed: %s", error_text("condition_eval_failed", exc))
            result = False

        next_position = step.condition_true_step if result else step.condition_false_step
        return StepResult(
            step_id=step.id,
            position=step.position,
            name=step.name,
            step_type=step.step_type,
            status="success",
            output={"condition_result": result, "next_position": next_position},
        )
    def _evaluate_condition_expression(self, expr: str, context: dict[str, Any]) -> bool:
        return evaluate_condition_expression(expr, context, StepResult)
