"""Tool implementations for orchestrator agent patterns."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.orchestrator_service import (
    complete_orchestrator_run,
    create_orchestrator_run,
    get_orchestrator_run,
)
from .context import ToolContext


class StartOrchestratorTool:
    name = "start_orchestrator"
    description = "Start a new orchestrator run that coordinates child agents."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        pattern = str(params.get("pattern", "single"))
        total_steps = max(1, int(params.get("total_steps", 1) or 1))
        max_iterations = max(1, min(int(params.get("max_iterations", 3) or 3), 10))
        routing_policy = params.get("routing_policy") or {}
        delegation_policy = params.get("delegation_policy") or {}

        session_id = None
        project_id = None
        if context:
            session_id = getattr(context, "session_id", None)
            project_id = getattr(context, "project_id", None)

        if not session_id:
            return {"error": "session_id is required in tool context"}

        db_gen = get_db()
        db: AsyncSession = await db_gen.__anext__()

        run = await create_orchestrator_run(
            db,
            session_id=session_id,
            project_id=project_id,
            pattern_type=pattern,
            total_steps=total_steps,
            routing_policy_json=routing_policy if isinstance(routing_policy, dict) else {},
            delegation_policy_json=delegation_policy if isinstance(delegation_policy, dict) else {},
            max_iterations=max_iterations,
        )
        await db.commit()

        return {
            "run_id": run.id,
            "pattern": pattern,
            "status": run.status,
            "total_steps": total_steps,
            "message": f"Orchestrator run started with pattern '{pattern}'.",
        }


class CompleteOrchestratorTool:
    name = "complete_orchestrator"
    description = "Mark the orchestrator run as completed with final output."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        run_id = str(params.get("run_id", ""))
        final_output = params.get("final_output") or {}
        summary = str(params.get("summary", ""))

        if not run_id:
            return {"error": "run_id is required"}

        db_gen = get_db()
        db: AsyncSession = await db_gen.__anext__()

        run = await get_orchestrator_run(db, run_id=run_id)
        if not run:
            return {"error": f"Orchestrator run not found: {run_id}"}

        await complete_orchestrator_run(db, run, final_output=final_output)
        await db.commit()

        return {
            "status": "completed",
            "run_id": run_id,
            "summary": summary or "Orchestrator run completed.",
            "final_output": final_output,
        }
