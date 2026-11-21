"""Orchestrator agent run service — create, delegate, merge, resolve, complete."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session
from ..models.agent.orchestrator_agent import (
    ORCHESTRATOR_PATTERN_EVALUATOR_OPTIMIZER,
    ORCHESTRATOR_PATTERN_PARALLEL,
    ORCHESTRATOR_PATTERN_REVIEWER_CRITIC,
    ORCHESTRATOR_PATTERN_SEQUENTIAL,
    ORCHESTRATOR_PATTERN_SUPERVISOR,
    ORCHESTRATOR_STATUS_COMPLETED,
    ORCHESTRATOR_STATUS_FAILED,
    ORCHESTRATOR_STATUS_RUNNING,
    ORCHESTRATOR_STATUS_WAITING_CHILDREN,
    ORCHESTRATOR_STATUSES,
    OrchestratorAgentRun,
)
from ..time_utils import utc_now


async def create_orchestrator_run(
    db: AsyncSession,
    *,
    session_id: str,
    parent_session_id: str | None = None,
    project_id: str | None = None,
    pattern_type: str,
    agent_definition_id: str | None = None,
    flow_definition_version_id: str | None = None,
    flow_node_id: str | None = None,
    total_steps: int = 1,
    routing_policy_json: dict[str, Any] | None = None,
    delegation_policy_json: dict[str, Any] | None = None,
    max_iterations: int = 3,
    child_session_ids: list[str] | None = None,
) -> OrchestratorAgentRun:
    """Create a new orchestrator run record."""
    run = OrchestratorAgentRun(
        id=str(uuid.uuid4()),
        session_id=session_id,
        parent_session_id=parent_session_id,
        project_id=project_id,
        pattern_type=pattern_type,
        agent_definition_id=agent_definition_id,
        flow_definition_version_id=flow_definition_version_id,
        flow_node_id=flow_node_id,
        total_steps=total_steps,
        current_step_index=0,
        routing_policy_json=routing_policy_json or {},
        delegation_policy_json=delegation_policy_json or {},
        max_iterations=max_iterations,
        child_session_ids_json=child_session_ids or [],
        status=ORCHESTRATOR_STATUS_RUNNING,
    )
    db.add(run)
    await db.flush()
    return run


async def get_orchestrator_run(
    db: AsyncSession,
    *,
    run_id: str,
) -> OrchestratorAgentRun | None:
    """Fetch an orchestrator run by ID."""
    result = await db.execute(select(OrchestratorAgentRun).where(OrchestratorAgentRun.id == run_id))
    return result.scalar_one_or_none()


async def get_orchestrator_runs_for_session(
    db: AsyncSession,
    *,
    session_id: str,
    pattern_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[OrchestratorAgentRun]:
    """List orchestrator runs for a session."""
    q = select(OrchestratorAgentRun).where(OrchestratorAgentRun.session_id == session_id)
    if pattern_type:
        q = q.where(OrchestratorAgentRun.pattern_type == pattern_type)
    if status:
        q = q.where(OrchestratorAgentRun.status == status)
    q = q.order_by(OrchestratorAgentRun.created_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def add_child_session(
    db: AsyncSession,
    run: OrchestratorAgentRun,
    child_session_id: str,
) -> None:
    """Append a child session ID to the run's child list."""
    child_ids = list(run.child_session_ids_json or [])
    if child_session_id not in child_ids:
        child_ids.append(child_session_id)
        run.child_session_ids_json = child_ids
        run.last_child_id = child_session_id
    await db.flush()


async def advance_sequential_step(
    db: AsyncSession,
    run: OrchestratorAgentRun,
) -> OrchestratorAgentRun:
    """Increment step index for a sequential pattern. Marks completed if all steps done."""
    if run.pattern_type != ORCHESTRATOR_PATTERN_SEQUENTIAL:
        raise ValueError(f"advance_sequential_step only valid for sequential, got {run.pattern_type}")
    run.current_step_index = (run.current_step_index or 0) + 1
    if run.current_step_index >= run.total_steps:
        run.status = ORCHESTRATOR_STATUS_COMPLETED
        run.completed_at = utc_now()
    else:
        run.status = ORCHESTRATOR_STATUS_RUNNING
    await db.flush()
    return run


async def mark_orchestrator_waiting_children(
    db: AsyncSession,
    run: OrchestratorAgentRun,
) -> OrchestratorAgentRun:
    """Mark orchestrator as waiting for child sessions to complete."""
    run.status = ORCHESTRATOR_STATUS_WAITING_CHILDREN
    await db.flush()
    return run


async def merge_child_output(
    db: AsyncSession,
    run: OrchestratorAgentRun,
    child_session_id: str,
    child_output: dict[str, Any],
    *,
    merge_strategy: str = "append",
) -> OrchestratorAgentRun:
    """Merge a completed child's output into the run's merged_output_json."""
    current = dict(run.merged_output_json or {})
    if merge_strategy == "append":
        # Append as a new key
        if "children" not in current:
            current["children"] = []
        current["children"].append({"child_session_id": child_session_id, "output": child_output})
    elif merge_strategy == "replace":
        # Replace existing with same key
        current[child_session_id] = child_output
    else:
        # Deep merge
        for k, v in (child_output or {}).items():
            if k in current and isinstance(current[k], dict) and isinstance(v, dict):
                current[k] = {**current[k], **v}
            else:
                current[k] = v
    run.merged_output_json = current
    await db.flush()
    return run


async def resolve_conflict(
    db: AsyncSession,
    run: OrchestratorAgentRun,
    conflict_key: str,
    resolution: dict[str, Any],
    *,
    winner_session_id: str | None = None,
    notes: str | None = None,
) -> OrchestratorAgentRun:
    """Record a conflict resolution."""
    resolutions = list(run.conflict_resolutions_json or [])
    resolutions.append({
        "conflict_key": conflict_key,
        "resolution": resolution,
        "winner_session_id": winner_session_id,
        "notes": notes,
        "resolved_at": str(utc_now()),
    })
    run.conflict_resolutions_json = resolutions
    await db.flush()
    return run


async def submit_review(
    db: AsyncSession,
    run: OrchestratorAgentRun,
    score: str,
    notes: str | None = None,
    *,
    revision_count: int | None = None,
) -> OrchestratorAgentRun:
    """Record a reviewer/critic or evaluator score."""
    run.last_review_score = score
    run.last_review_notes = notes
    if revision_count is not None:
        run.revision_count = revision_count
    else:
        run.revision_count = (run.revision_count or 0) + 1

    # For reviewer_critic: on fail → increment revision, on pass → complete
    # For evaluator_optimizer: check max_iterations
    if run.pattern_type == ORCHESTRATOR_PATTERN_REVIEWER_CRITIC:
        if score in {"pass", "approved"}:
            run.status = ORCHESTRATOR_STATUS_COMPLETED
            run.completed_at = utc_now()
        else:
            # Fail → continue, agent should revise
            run.status = ORCHESTRATOR_STATUS_RUNNING
    elif run.pattern_type == ORCHESTRATOR_PATTERN_EVALUATOR_OPTIMIZER:
        if score in {"pass", "approved", "success"}:
            run.status = ORCHESTRATOR_STATUS_COMPLETED
            run.completed_at = utc_now()
        elif (run.revision_count or 0) >= run.max_iterations:
            # Max iterations reached → fail
            run.status = ORCHESTRATOR_STATUS_FAILED
            run.completed_at = utc_now()
            run.last_error = f"Max iterations ({run.max_iterations}) reached without passing score"
        else:
            run.status = ORCHESTRATOR_STATUS_RUNNING

    await db.flush()
    return run


async def complete_orchestrator_run(
    db: AsyncSession,
    run: OrchestratorAgentRun,
    *,
    status: str = ORCHESTRATOR_STATUS_COMPLETED,
    final_output: dict[str, Any] | None = None,
    error: str | None = None,
) -> OrchestratorAgentRun:
    """Mark an orchestrator run as completed or failed."""
    if status not in ORCHESTRATOR_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    run.status = status
    run.completed_at = utc_now()
    if final_output:
        current = dict(run.merged_output_json or {})
        current["final"] = final_output
        run.merged_output_json = current
    if error:
        run.last_error = error
    await db.flush()
    return run


async def cancel_orchestrator_run(
    db: AsyncSession,
    run: OrchestratorAgentRun,
    *,
    error: str | None = None,
) -> OrchestratorAgentRun:
    """Cancel an orchestrator run."""
    return await complete_orchestrator_run(
        db, run, status="cancelled", error=error or "Cancelled by user"
    )


async def is_orchestrator_terminal(
    db: AsyncSession,
    run: OrchestratorAgentRun,
) -> bool:
    """Return True if the run is in a terminal state."""
    if run.status in {ORCHESTRATOR_STATUS_COMPLETED, ORCHESTRATOR_STATUS_FAILED, "cancelled"}:
        return True
    # For supervisor/sequential/parallel: check if all children are done
    if run.pattern_type in {
        ORCHESTRATOR_PATTERN_SUPERVISOR,
        ORCHESTRATOR_PATTERN_SEQUENTIAL,
        ORCHESTRATOR_PATTERN_PARALLEL,
        ORCHESTRATOR_PATTERN_REVIEWER_CRITIC,
        ORCHESTRATOR_PATTERN_EVALUATOR_OPTIMIZER,
    }:
        child_ids = list(run.child_session_ids_json or [])
        if not child_ids:
            return False
        # Check if all child sessions are in terminal state
        result = await db.execute(
            select(Session).where(Session.id.in_(child_ids))
        )
        child_sessions = result.scalars().all()
        terminal = {"completed", "error", "stopped", "failed"}
        return all(s.status in terminal for s in child_sessions)
    return False
