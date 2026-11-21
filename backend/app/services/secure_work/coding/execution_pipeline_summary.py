"""Pipeline run summaries written while a coding agent execution starts: workspaces, context budget, session."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    User,
    WorkCodingPipelineRun,
    WorkCodingPipelineStage,
)
from ....time_utils import utc_now
from ..coding_serializers import serialize_coding_pipeline_run
from .coding_runtime_contract import coding_execution_contract
from .coding_state_machine import evaluate_coding_state_machine
from .execution_prompt import _context_budget_summary


def _with_workspace_summary(
    pipeline_run: dict[str, Any],
    workspaces: list[dict[str, Any]],
    *,
    state_machine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = dict(pipeline_run)
    summary = dict(updated.get("summary") or {})
    summary["workspaces"] = workspaces
    if state_machine is not None:
        summary["state_machine"] = state_machine
        summary["coding_execution_contract"] = coding_execution_contract(state_machine)
    updated["summary"] = summary
    recovery_state = dict(updated.get("recovery_state") or {})
    recovery_state["workspace_ids"] = [
        str(workspace.get("id") or "") for workspace in workspaces if workspace.get("id")
    ]
    updated["recovery_state"] = recovery_state
    return updated


def _with_context_budget_summary(pipeline_run: dict[str, Any], context_budget: dict[str, Any]) -> dict[str, Any]:
    updated = dict(pipeline_run)
    summary = dict(updated.get("summary") or {})
    summary["context_budget"] = _context_budget_summary(context_budget)
    updated["summary"] = summary
    return updated


async def _persist_pipeline_workspace_summary(
    db: AsyncSession,
    *,
    pipeline_run_id: str,
    workspaces: list[dict[str, Any]],
    current_user: User,
) -> dict[str, Any] | None:
    if not pipeline_run_id:
        return None
    run = await db.get(WorkCodingPipelineRun, pipeline_run_id)
    if run is None:
        return None
    summary = {**dict(run.summary_json or {}), "workspaces": workspaces}
    stages = await _pipeline_stages(db, run.id)
    state_machine = evaluate_coding_state_machine(stages, summary=summary, run_status=run.status)
    summary["state_machine"] = state_machine
    summary["coding_execution_contract"] = coding_execution_contract(state_machine)
    run.summary_json = summary
    run.recovery_state_json = {
        **dict(run.recovery_state_json or {}),
        "workspace_ids": [str(workspace.get("id") or "") for workspace in workspaces if workspace.get("id")],
    }
    run.updated_by = current_user.id
    run.updated_at = utc_now()
    return state_machine


async def _persist_pipeline_context_budget(
    db: AsyncSession,
    *,
    pipeline_run_id: str,
    context_budget: dict[str, Any],
    current_user: User,
) -> None:
    if not pipeline_run_id:
        return
    run = await db.get(WorkCodingPipelineRun, pipeline_run_id)
    if run is None:
        return
    run.summary_json = {**dict(run.summary_json or {}), "context_budget": _context_budget_summary(context_budget)}
    run.updated_by = current_user.id
    run.updated_at = utc_now()


async def _mark_pipeline_agent_session_started(
    db: AsyncSession,
    *,
    pipeline_run_id: str,
    session_id: str,
    current_user: User,
) -> dict[str, Any] | None:
    if not pipeline_run_id:
        return None
    run = await db.get(WorkCodingPipelineRun, pipeline_run_id)
    if run is None:
        return None
    now = utc_now()
    summary = dict(run.summary_json or {})
    summary["agent_session"] = {
        "session_id": session_id,
        "chat_url": f"/chat?session_id={session_id}",
        "started_at": now.isoformat(),
    }
    run.summary_json = summary
    run.recovery_state_json = {
        **dict(run.recovery_state_json or {}),
        "agent_session_id": session_id,
        "agent_chat_url": f"/chat?session_id={session_id}",
    }
    stages = await _pipeline_stages(db, run.id)
    if stages:
        stages[0].status = "completed"
        stages[0].completed_at = stages[0].completed_at or now
        stages[0].updated_by = current_user.id
    if len(stages) > 1 and stages[1].status in {"pending", "ready"}:
        stages[1].status = "running"
        stages[1].started_at = stages[1].started_at or now
        stages[1].updated_by = current_user.id
        run.current_stage_key = stages[1].stage_key
    summary["state_machine"] = evaluate_coding_state_machine(stages, summary=summary, run_status=run.status)
    summary["coding_execution_contract"] = coding_execution_contract(summary["state_machine"])
    run.summary_json = summary
    run.updated_by = current_user.id
    run.updated_at = now
    await db.flush()
    return serialize_coding_pipeline_run(run, stages)


async def _pipeline_stages(db: AsyncSession, run_id: str) -> list[WorkCodingPipelineStage]:
    return (
        await db.execute(
            select(WorkCodingPipelineStage)
            .where(WorkCodingPipelineStage.run_id == run_id)
            .order_by(WorkCodingPipelineStage.stage_order.asc())
        )
    ).scalars().all()
