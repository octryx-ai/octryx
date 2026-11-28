"""Task steps that run agents: one analysis turn, or a sub-agent turn per item."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

# These are imported at module level so tests can patch them cleanly.
from ...db import async_session_factory
from ...services.agent_definition_execution_outcomes import (
    payload_resolution_metadata,
)
from ...services.devices.agent_runtime import runner_turn
from ...services.run_capability.schedule_capability import schedule_session_capability_metadata
from ._step_context import (
    extract_items_for_spawn,
)
from ._step_result import StepResult

if TYPE_CHECKING:
    from ...models.project.task import Task, TaskRun, TaskStep

logger = logging.getLogger(__name__)


class AgentStepKinds:
    async def _exec_analysis(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
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
    async def _exec_sub_agent_spawn(
        self,
        step: TaskStep,
        context: dict,
        db: Any,
        task: Task,
        task_run: TaskRun,
    ) -> StepResult:
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
                        turn = await runner_turn(sub_db, user_id=task.owner_id, prompt=prompt,
                                                 session_id=sub_session_id)
                        result_payload = {"session_id": sub_session_id, "response": turn.answer}
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
    def _extract_items_for_spawn(self, step: TaskStep, context: dict) -> list:
        return extract_items_for_spawn(step, context, StepResult)
