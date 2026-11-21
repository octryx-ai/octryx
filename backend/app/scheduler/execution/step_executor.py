"""Generic Task Step Executor.

Executes ordered TaskStep records for a Task.  Each step type has its own
handler; the outputs are accumulated in a shared context dict that subsequent
steps can reference via dot-notation field refs (e.g. ``steps.1.output.results``).

No Jira / Bitbucket / project-specific logic lives here – all domain knowledge
is encoded in the TaskStep records configured by the operator.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.services.error_facts import error_text

from ...agent.engine import run_agent

# These are imported at module level so tests can patch them cleanly.
from ...db import async_session_factory
from ...models.runtime.product_run import RUN_ORIGIN_SCHEDULED_TASK
from ...services.agent_definition_execution_outcomes import (
    AgentDefinitionExecutionError,
    payload_resolution_metadata,
)
from ...services.run_capability.schedule_capability import schedule_session_capability_metadata
from ._step_agent_loader import load_agent_for_step
from ._step_conditions import eval_condition_ast, evaluate_condition_expression, normalize_condition_value
from ._step_connector_execution import deduplicate_items, execute_connector_action
from ._step_context import (
    build_step_prompt,
    extract_items_for_spawn,
    render_template_params,
    render_template_str,
    resolve_field,
)
from ._step_verification import build_verification_prompt, classify_verification_response

if TYPE_CHECKING:
    from ...models.project.task import Task, TaskRun, TaskStep

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    step_id: str
    position: int
    name: str
    step_type: str
    status: str  # success | error | skipped
    output: dict = field(default_factory=dict)
    error: str | None = None
    fix_attempts: int = 0
    session_ids: list[str] = field(default_factory=list)
    #Typed explicit refusal, e.g. an agent definition the platform cannot
    #: execute. Identifiers and codes only, so it is safe in the persisted step log.
    refusal: dict | None = None

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "position": self.position,
            "name": self.name,
            "step_type": self.step_type,
            "status": self.status,
            "error": self.error,
            "fix_attempts": self.fix_attempts,
            "session_ids": self.session_ids,
            "refusal": self.refusal,
            # keep output lightweight in the log
            "output_keys": list(self.output.keys()) if self.output else [],
        }


def _render_action_summary_message(summary: dict[str, Any]) -> str:
    title = str(summary.get("title") or "Action Summary").strip()
    project_name = str(summary.get("project_name") or "").strip()
    prompt_contract = str(summary.get("prompt_contract") or "").strip()
    primary_model = str(summary.get("primary_model") or "").strip()
    scanned = summary.get("scanned")
    enriched = summary.get("enriched")
    created = summary.get("created")
    updated_count = summary.get("updated")
    skipped = summary.get("skipped")
    lines = [f"{title} completed."]
    if project_name:
        lines.append(f"Project: {project_name}")
    counts = []
    if scanned is not None:
        counts.append(f"scanned {scanned}")
    if enriched is not None:
        counts.append(f"enriched {enriched}")
    if created is not None:
        counts.append(f"created {created}")
    if updated_count is not None:
        counts.append(f"updated {updated_count}")
    if skipped is not None:
        counts.append(f"skipped {skipped}")
    if counts:
        lines.append("Result: " + ", ".join(counts) + ".")
    if primary_model:
        lines.append(f"Primary model: {primary_model}")
    if prompt_contract:
        lines.append(f"Prompt contract: {prompt_contract}")

    entries = summary.get("entries") if isinstance(summary.get("entries"), list) else []
    changed = [
        entry
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("status") or "").strip().lower() in {"created", "updated"}
    ][:5]
    if changed:
        lines.append("")
        lines.append("Changed entries:")
        for entry in changed:
            key = str(entry.get("silver_key") or entry.get("gold_key") or "").strip()
            confidence = entry.get("confidence")
            concepts = ", ".join(str(item) for item in (entry.get("concepts") or [])[:3])
            title_text = str(entry.get("title") or "").strip()
            review_status = str(entry.get("review_status") or "").strip()
            preview = str(entry.get("summary_preview") or "").strip()
            detail = f"- {key}" if key else "- Entry"
            if confidence is not None:
                detail += f" confidence={confidence}"
            if review_status:
                detail += f" review={review_status}"
            if concepts:
                detail += f" concepts={concepts}"
            lines.append(detail)
            if title_text:
                lines.append(f"  Title: {title_text}")
            if preview:
                lines.append(f"  Summary: {preview}")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class StepExecutor:
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
        """Persist explicit safe action summaries into the run session."""
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
    # connector_fetch
    # ------------------------------------------------------------------

    async def _exec_connector_fetch(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        """Call a connector tool directly.  Deduplicates list results against task state."""
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
        """Return only items whose (id, updated_at) pair has changed since last run."""
        return deduplicate_items(items, task)

    # ------------------------------------------------------------------
    # analysis
    # ------------------------------------------------------------------

    async def _exec_analysis(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        """Run an agent with the step's instructions + piped context."""
        prompt = self._build_step_prompt(step, context)
        agent_def, runtime_target_id, thinking_level = await self._load_agent_for_step(step, task, db)
        max_iters = int((task.config or {}).get("max_iterations") or 32)

        session, result_payload = await self.scheduler._run_agent_for_task(
            db,
            task,
            prompt,
            agent_definition=agent_def,
            runtime_target_id=runtime_target_id,
            thinking_level=thinking_level,
            session_metadata={
                "title": f"{task.name} · {step.name} · {task_run.id[:8]}",
                "task_id": task.id,
                "task_name": task.name,
                "task_run_id": task_run.id,
                "step_id": step.id,
                "step_name": step.name,
                "trigger": "task_step",
                # Which agent-definition source produced these instructions.
                **payload_resolution_metadata(agent_def),
            },
            max_iterations=max_iters,
            skip_session_reuse=True,
            parent_session_id=task_run.session_id,
        )

        return StepResult(
            step_id=step.id,
            position=step.position,
            name=step.name,
            step_type=step.step_type,
            status="success",
            output=result_payload,
            session_ids=[session.id],
        )

    # ------------------------------------------------------------------
    # sub_agent_spawn
    # ------------------------------------------------------------------

    async def _exec_sub_agent_spawn(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        """Spawn one agent per item from context, respecting max_concurrent_agents."""
        from ...models.session.session import Session

        items = self._extract_items_for_spawn(step, context)
        if not items:
            return StepResult(
                step_id=step.id,
                position=step.position,
                name=step.name,
                step_type=step.step_type,
                status="success",
                output={"spawned": 0, "results": [], "info": "No new items to process"},
            )

        agent_def, runtime_target_id, thinking_level = await self._load_agent_for_step(step, task, db)
        agent_type = (agent_def or {}).get("agentType") or task.agent_type or "change"
        max_concurrent = max(1, task.max_concurrent_agents or 3)
        semaphore = asyncio.Semaphore(max_concurrent)
        parent_session_id = task_run.session_id

        # Pre-create all sub-sessions so they're immediately visible in the UI
        sub_session_ids: list[str] = []
        async with async_session_factory() as setup_db:
            for item in items:
                item_label = str(item.get("key") or item.get("id") or item.get("ticket_id") or item)[:80]
                sub_sess = Session(
                    id=str(uuid.uuid4()),
                    user_id=task.owner_id,
                    project_id=task.project_id,
                    agent_type=agent_type,
                    status="active",
                    origin="scheduler",
                    metadata_={
                        "title": f"{step.name} · {item_label}",
                        "task_id": task.id,
                        "task_run_id": task_run.id,
                        "step_id": step.id,
                        "trigger": "sub_agent_spawn",
                        "item": item,
                        **schedule_session_capability_metadata(task),
                        # The spawned sub-sessions execute the same resolved
                        # definition, so they record the same provenance entry.
                        **payload_resolution_metadata(agent_def),
                    },
                    parent_session_id=parent_session_id,
                    sub_agent_depth=1,
                )
                setup_db.add(sub_sess)
                sub_session_ids.append(sub_sess.id)
            await setup_db.commit()

        async def _run_one(item: Any, sub_session_id: str) -> dict:
            async with semaphore:
                prompt = self._build_step_prompt(step, context, item=item)
                try:
                    async with async_session_factory() as sub_db:
                        result_payload: dict = {"session_id": sub_session_id}
                        async for event in run_agent(
                            session_id=sub_session_id,
                            user_message=prompt,
                            user_id=task.owner_id,
                            project_id=task.project_id,
                            agent_type=agent_type,
                            db=sub_db,
                            runtime_target_id=runtime_target_id,
                            thinking_level=thinking_level,
                            agent_definition=agent_def,
                            parent_session_id=parent_session_id,
                            sub_agent_depth=1,
                            max_iterations=step.agent_timeout_seconds // 10 if step.agent_timeout_seconds else 30,
                            run_origin=RUN_ORIGIN_SCHEDULED_TASK,
                        ):
                            if event.role == "assistant" and event.content:
                                result_payload["response"] = event.content
                        return {
                            "item": item,
                            "session_id": sub_session_id,
                            "result": result_payload,
                            "status": "completed",
                        }
                except Exception as exc:
                    logger.exception("[step_executor] sub_agent for item %s failed", item)
                    return {
                        "item": item,
                        "session_id": sub_session_id,
                        "status": "failed",
                        "error": str(exc),
                    }

        raw = await asyncio.gather(
            *[_run_one(item, sid) for item, sid in zip(items, sub_session_ids)],
            return_exceptions=True,
        )
        results = [r if not isinstance(r, Exception) else {"status": "failed", "error": str(r)} for r in raw]

        return StepResult(
            step_id=step.id,
            position=step.position,
            name=step.name,
            step_type=step.step_type,
            status="success",
            output={
                "spawned": len(items),
                "completed": sum(1 for r in results if r.get("status") == "completed"),
                "failed": sum(1 for r in results if r.get("status") == "failed"),
                "results": results,
            },
            session_ids=[r["session_id"] for r in results if r.get("session_id")],
        )

    # ------------------------------------------------------------------
    # verification
    # ------------------------------------------------------------------

    async def _exec_verification(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        """Run a verification agent; retry up to max_fix_attempts on failure."""
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

    # ------------------------------------------------------------------
    # output
    # ------------------------------------------------------------------

    async def _exec_output(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        """Call a connector tool with rendered context params, or run an agent."""
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

    # ------------------------------------------------------------------
    # condition
    # ------------------------------------------------------------------

    async def _exec_condition(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
        """Evaluate a Python expression and branch to the appropriate next step."""
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize_condition_value(self, value: Any) -> Any:
        return normalize_condition_value(value, StepResult)

    def _eval_condition_ast(self, node: Any, names: dict[str, Any]) -> Any:
        return eval_condition_ast(node, names)

    def _evaluate_condition_expression(self, expr: str, context: dict[str, Any]) -> bool:
        return evaluate_condition_expression(expr, context, StepResult)

    def _build_step_prompt(
        self,
        step: TaskStep,
        context: dict,
        item: Any = None,
    ) -> str:
        """Build the agent prompt: task name + step instructions + piped context + optional item."""
        return build_step_prompt(step, context, StepResult, item=item)

    def _extract_items_for_spawn(self, step: TaskStep, context: dict) -> list:
        """Find the list of items to spawn sub-agents for."""
        return extract_items_for_spawn(step, context, StepResult)

    def _resolve_field(self, ref: str, context: dict) -> Any:
        """Resolve a dot-notation path like ``steps.1.output.results.0.key`` into a value."""
        return resolve_field(ref, context, StepResult)

    def _render_template_params(self, params: dict, context: dict) -> dict:
        """Replace ``{{steps.1.output.key}}`` placeholders in all string param values."""
        return render_template_params(params, context, StepResult)

    def _render_template_str(self, template: str, context: dict) -> str:
        return render_template_str(template, context, StepResult)

    async def _load_agent_for_step(
        self,
        step: TaskStep,
        task: Task,
        db: Any,
    ) -> tuple[dict | None, str | None, str | None]:
        """Load the step agent selection and resolved execution settings."""
        return await load_agent_for_step(step, task, db, logger)
