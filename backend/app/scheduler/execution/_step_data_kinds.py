"""Task steps that move data: a connector fetch (deduplicated against the task's state) and the output step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# These are imported at module level so tests can patch them cleanly.
from ._step_connector_execution import deduplicate_items, execute_connector_action
from ._step_result import StepResult

if TYPE_CHECKING:
    from ...models.project.task import Task, TaskRun, TaskStep


class DataStepKinds:
    async def _exec_connector_fetch(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        if not step.connector_action:
            return StepResult(
                step_id=step.id,
                position=step.position,
                name=step.name,
                step_type=step.step_type,
                status="error",
                error="connector_action is required for connector_fetch steps",
            )

        result = await execute_connector_action(
            step=step,
            context=context,
            db=db,
            task=task,
            task_run=task_run,
            render_template_params=self._render_template_params,
        )

        if "error" in result:
            return StepResult(
                step_id=step.id,
                position=step.position,
                name=step.name,
                step_type=step.step_type,
                status="error",
                error=result["error"],
                output=result,
            )

        # Deduplication for list-type results
        items = result.get("results") or result.get("items") or []
        if items:
            new_items, state_update = self._deduplicate_items(items, task)
            if state_update:
                config = dict(task.config or {})
                items_state = dict(config.get("_items_state", {}))
                items_state.update(state_update)
                config["_items_state"] = items_state
                task.config = config
                await db.commit()
            result["new_items"] = new_items
            result["new_item_count"] = len(new_items)
            result["total_item_count"] = len(items)

        return StepResult(
            step_id=step.id,
            position=step.position,
            name=step.name,
            step_type=step.step_type,
            status="success",
            output=result,
        )
    def _deduplicate_items(self, items: list, task: Task) -> tuple[list, dict]:
        return deduplicate_items(items, task)
    async def _exec_output(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        if step.connector_action:
            result = await execute_connector_action(
                step=step,
                context=context,
                db=db,
                task=task,
                task_run=task_run,
                render_template_params=self._render_template_params,
            )
            status = "error" if "error" in result else "success"
            return StepResult(
                step_id=step.id,
                position=step.position,
                name=step.name,
                step_type=step.step_type,
                status=status,
                output=result,
                error=result.get("error"),
            )

        # No connector – treat as a summarising analysis step
        return await self._exec_analysis(step, context, db, task, task_run)
