"""Run bookkeeping shared by every entry point: failure, acceptance, progress, checkpoints and audit."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog
from ....models.agent.orchestrator_agent import OrchestratorAgentRun
from ...flow_runtime_governance import FlowRuntimeLimits
from ...runtime_acceptance import (
    derive_runtime_acceptance_state,
    record_runtime_acceptance,
    runtime_acceptance_state,
)
from ...runtime_failure_taxonomy import classify_runtime_failure, record_runtime_failure
from ..planning import update_flow_plan_step
from ..recovery import touch_flow_run_lease


def _set_runtime_failure(
    orchestrator_run: OrchestratorAgentRun,
    error: BaseException | None,
    *,
    source: str,
    node_id: str | None = None,
    node_type: str | None = None,
    required_action: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failure = classify_runtime_failure(
        error,
        source=source,
        node_id=node_id,
        node_type=node_type,
        required_action=required_action,
        detail=detail,
    )
    record_runtime_failure(orchestrator_run, failure)
    return failure


async def _sync_runtime_acceptance(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    run: OrchestratorAgentRun,
    node_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    previous_state = str(runtime_acceptance_state(run).get("state") or "")
    acceptance = derive_runtime_acceptance_state(run, reason=reason)
    record_runtime_acceptance(run, acceptance)
    if previous_state != acceptance["state"]:
        await _audit_flow_event(
            db,
            user_id=user_id,
            session_id=session_id,
            action="flow.acceptance_state_changed",
            run=run,
            node_id=node_id,
            details={"previous_state": previous_state or None, "acceptance": acceptance},
        )
    return acceptance


def _set_run_progress(
    orchestrator_run: OrchestratorAgentRun,
    *,
    node_index: int,
    node_id: str,
    phase: str,
    reason: str | None = None,
    required_action: str | None = None,
) -> None:
    orchestrator_run.current_step_index = max(0, node_index)
    touch_flow_run_lease(orchestrator_run, node_id=node_id, phase=phase)
    update_flow_plan_step(
        orchestrator_run,
        node_id=node_id,
        status=_plan_status_from_phase(phase),
        reason=reason,
        required_action=required_action,
    )


def _plan_status_from_phase(phase: str) -> str:
    if phase == "completed":
        return "done"
    if phase == "paused":
        return "blocked"
    if phase == "resuming":
        return "running"
    if phase in {"running", "skipped", "failed", "cancelled"}:
        return phase
    return "pending"


async def _commit_flow_checkpoint(
    db: AsyncSession,
    *objects: Any,
) -> None:
    await db.flush()
    await db.commit()
    for item in objects:
        await db.refresh(item)


async def _audit_flow_event(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    action: str,
    run: OrchestratorAgentRun,
    node_id: str,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            session_id=session_id,
            action=action,
            resource_type="flow_run",
            resource_id=run.id,
            details={
                "flow_run_id": run.id,
                "flow_definition_version_id": run.flow_definition_version_id,
                "node_id": node_id,
                **details,
            },
        )
    )
    await db.flush()


def _serialize_limits(limits: FlowRuntimeLimits) -> dict[str, Any]:
    return {
        "max_nodes": limits.max_nodes,
        "max_tool_calls": limits.max_tool_calls,
        "max_run_seconds": limits.max_run_seconds,
    }
