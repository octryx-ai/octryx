"""API routes for orchestrator agent runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models.security.user import User
from ...services.access_control import require_project_access
from ...services.auth import get_current_user
from ...services.orchestrator_service import (
    add_child_session,
    advance_sequential_step,
    cancel_orchestrator_run,
    complete_orchestrator_run,
    create_orchestrator_run,
    get_orchestrator_run,
    get_orchestrator_runs_for_session,
    merge_child_output,
    resolve_conflict,
    submit_review,
)
from ...services.session.resource_access import (
    require_matching_project,
    require_record_access,
    require_session_resource_access,
)
from ._orchestrator_models import (
    OrchestratorAddChildRequest,
    OrchestratorCompleteRequest,
    OrchestratorConflictRequest,
    OrchestratorCreateRequest,
    OrchestratorMergeRequest,
    OrchestratorReviewRequest,
    OrchestratorRunResponse,
)

router = APIRouter(prefix="/api/v1/orchestrator", tags=["orchestrator"])

RUN_NOT_FOUND_DETAIL = "Orchestrator run not found"


def _unfenced(value):
    from ...services.content_security.knowledge_fence import unfenced_result

    return unfenced_result(value)


async def _accessible_run(db: AsyncSession, run_id: str, user: User, *, require_write: bool):
    """The run when the caller may use its session: 404 unseen or unknown, 403 lower role."""
    run = await get_orchestrator_run(db, run_id=run_id)
    await require_record_access(
        db, run, user_id=user.id, not_found_detail=RUN_NOT_FOUND_DETAIL, require_write=require_write
    )
    return run


def _serialize_run(run) -> dict:
    """Serialize an OrchestratorAgentRun to a dict for the API."""
    return {
        "id": run.id,
        "session_id": run.session_id,
        "parent_session_id": run.parent_session_id,
        "project_id": run.project_id,
        "pattern_type": run.pattern_type,
        "agent_definition_id": run.agent_definition_id,
        "flow_definition_version_id": run.flow_definition_version_id,
        "flow_node_id": run.flow_node_id,
        "current_step_index": run.current_step_index,
        "total_steps": run.total_steps,
        "child_session_ids_json": run.child_session_ids_json,
        # An exit to people: node outputs keep their fences for the agent nodes that read them, never in the UI.
        "merged_output_json": _unfenced(run.merged_output_json),
        "conflict_resolutions_json": run.conflict_resolutions_json,
        "reviewer_session_id": run.reviewer_session_id,
        "last_review_score": run.last_review_score,
        "last_review_notes": run.last_review_notes,
        "revision_count": run.revision_count,
        "max_iterations": run.max_iterations,
        "routing_policy_json": run.routing_policy_json,
        "delegation_policy_json": run.delegation_policy_json,
        "status": run.status,
        "last_child_id": run.last_child_id,
        "last_error": run.last_error,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


# ---- Routes ----


@router.post("", response_model=OrchestratorRunResponse)
async def create_run(
    req: OrchestratorCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new orchestrator run for a session the caller may write."""
    await require_project_access(db, current_user.id, req.project_id)
    session = await require_session_resource_access(
        db, session_id=req.session_id, user_id=current_user.id, require_write=True
    )
    if req.parent_session_id:
        await require_session_resource_access(db, session_id=req.parent_session_id, user_id=current_user.id)
    run = await create_orchestrator_run(
        db,
        session_id=req.session_id,
        parent_session_id=req.parent_session_id,
        project_id=require_matching_project(session, req.project_id),
        pattern_type=req.pattern_type,
        agent_definition_id=req.agent_definition_id,
        flow_definition_version_id=req.flow_definition_version_id,
        flow_node_id=req.flow_node_id,
        total_steps=req.total_steps,
        routing_policy_json=req.routing_policy_json,
        delegation_policy_json=req.delegation_policy_json,
        max_iterations=req.max_iterations,
    )
    await db.commit()
    return OrchestratorRunResponse(**_serialize_run(run))


@router.get("", response_model=list[OrchestratorRunResponse])
async def list_runs(
    session_id: str | None = Query(None),
    pattern_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List orchestrator runs, optionally filtered by session, pattern, or status."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    await require_session_resource_access(db, session_id=session_id, user_id=current_user.id)
    runs = await get_orchestrator_runs_for_session(
        db, session_id=session_id, pattern_type=pattern_type, status=status, limit=limit
    )
    return [OrchestratorRunResponse(**_serialize_run(r)) for r in runs]


@router.get("/{run_id}", response_model=OrchestratorRunResponse)
async def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific orchestrator run by ID."""
    run = await _accessible_run(db, run_id, current_user, require_write=False)
    return OrchestratorRunResponse(**_serialize_run(run))


@router.post("/add-child", response_model=OrchestratorRunResponse)
async def add_child(
    req: OrchestratorAddChildRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a child session ID to an existing orchestrator run."""
    run = await _accessible_run(db, req.run_id, current_user, require_write=True)
    await require_session_resource_access(db, session_id=req.child_session_id, user_id=current_user.id)
    await add_child_session(db, run, req.child_session_id)
    await db.commit()
    return OrchestratorRunResponse(**_serialize_run(run))


@router.post("/merge-child", response_model=OrchestratorRunResponse)
async def merge_child(
    req: OrchestratorMergeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Merge a child session's output into the orchestrator run."""
    run = await _accessible_run(db, req.run_id, current_user, require_write=True)
    await merge_child_output(db, run, req.child_session_id, req.child_output, merge_strategy=req.merge_strategy)
    await db.commit()
    return OrchestratorRunResponse(**_serialize_run(run))


@router.post("/resolve-conflict", response_model=OrchestratorRunResponse)
async def conflict_resolve(
    req: OrchestratorConflictRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a conflict resolution for an orchestrator run."""
    run = await _accessible_run(db, req.run_id, current_user, require_write=True)
    await resolve_conflict(
        db,
        run,
        req.conflict_key,
        req.resolution,
        winner_session_id=req.winner_session_id,
        notes=req.notes,
    )
    await db.commit()
    return OrchestratorRunResponse(**_serialize_run(run))


@router.post("/submit-review", response_model=OrchestratorRunResponse)
async def review(
    req: OrchestratorReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a reviewer/critic or evaluator score."""
    run = await _accessible_run(db, req.run_id, current_user, require_write=True)
    await submit_review(db, run, req.score, req.notes)
    await db.commit()
    return OrchestratorRunResponse(**_serialize_run(run))


@router.post("/advance-step", response_model=OrchestratorRunResponse)
async def advance_step(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Advance the step index for a sequential pattern."""
    run = await _accessible_run(db, run_id, current_user, require_write=True)
    await advance_sequential_step(db, run)
    await db.commit()
    return OrchestratorRunResponse(**_serialize_run(run))


@router.post("/complete", response_model=OrchestratorRunResponse)
async def complete(
    req: OrchestratorCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an orchestrator run as completed, failed, or cancelled."""
    run = await _accessible_run(db, req.run_id, current_user, require_write=True)
    await complete_orchestrator_run(db, run, status=req.status, final_output=req.final_output, error=req.error)
    await db.commit()
    return OrchestratorRunResponse(**_serialize_run(run))


@router.post("/{run_id}/cancel", response_model=OrchestratorRunResponse)
async def cancel(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an orchestrator run."""
    run = await _accessible_run(db, run_id, current_user, require_write=True)
    await cancel_orchestrator_run(db, run)
    await db.commit()
    return OrchestratorRunResponse(**_serialize_run(run))
