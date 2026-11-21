"""Traces, quality, evaluation, recovery, resume and cancel of flow runs.

Included into the ``/api/v1/flows`` router by ``flow_definitions.py``; this router has no prefix of its own. A partial
run starts in a Workspace (``flow_orchestration.start_scope``): without one the answer is 409 ``needs_configuration``
/ ``workspace_required`` before anything is written.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flow_orchestration.dag.approval_resume import resume_v2_flow_dag
from app.services.flow_orchestration.dag.cancellation import cancel_v2_flow_dag
from app.services.flow_orchestration.dag.interrupted import recover_stale_v2_flow_runs, resume_interrupted_v2_flow_dag

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.flow_orchestration.recovery import list_stale_v2_flow_runs
from ...services.flow_orchestration.start_scope import require_flow_start_workspace
from ...services.flow_quality import evaluate_flow_run, get_flow_run_quality_summary
from ...services.flow_test_cases import run_partial_flow_version
from ...services.flow_trace import get_flow_node_run_trace, get_flow_run_trace, serialize_flow_run
from ...services.notification_delivery import require_admin_user
from ...services.workflow_runs.records import WorkflowRunError
from ._workflow_run_http import _http

router = APIRouter()


@router.get("/runs/{run_id}/trace")
async def get_flow_run_trace_detail(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await get_flow_run_trace(db, run_id=run_id)


@router.get("/runs/stale")
async def get_stale_flow_runs(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    runs = await list_stale_v2_flow_runs(db, limit=limit)
    return {"items": [serialize_flow_run(run) for run in runs]}


@router.post("/runs/recover-stale")
async def post_recover_stale_flow_runs(
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    result = await recover_stale_v2_flow_runs(
        db,
        user_id=current_user.id,
        limit=int(body.get("limit") or 20),
        reason=str(body.get("reason") or "").strip() or None,
    )
    await db.commit()
    return result


@router.get("/runs/{run_id}/node-runs/{node_run_id}")
async def get_flow_node_run_trace_detail(
    run_id: str,
    node_run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await get_flow_node_run_trace(db, run_id=run_id, node_run_id=node_run_id)


@router.get("/runs/{run_id}/quality")
async def get_flow_run_quality(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await get_flow_run_quality_summary(db, run_id=run_id)


@router.post("/runs/{run_id}/evaluate")
async def post_flow_run_evaluation(
    run_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    result = await evaluate_flow_run(
        db,
        run_id=run_id,
        current_user=current_user,
        payload=payload if isinstance(payload, dict) else {},
    )
    await db.commit()
    return result


@router.post("/runs/{run_id}/resume")
async def post_resume_flow_run(
    run_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    try:
        run = await resume_v2_flow_dag(
            db,
            run_id=run_id,
            decision=str(body.get("decision") or "approve"),
            approval_id=str(body.get("approval_id") or "").strip() or None,
            human_input=body.get("human_input") if isinstance(body.get("human_input"), dict) else {},
            user_id=current_user.id,
            reason=str(body.get("reason") or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return await get_flow_run_trace(db, run_id=run.id)


@router.post("/runs/{run_id}/resume-interrupted")
async def post_resume_interrupted_flow_run(
    run_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    try:
        run = await resume_interrupted_v2_flow_dag(
            db,
            run_id=run_id,
            user_id=current_user.id,
            reason=str(body.get("reason") or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return await get_flow_run_trace(db, run_id=run.id)


@router.post("/runs/{run_id}/cancel")
async def post_cancel_flow_run(
    run_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    try:
        run = await cancel_v2_flow_dag(
            db,
            run_id=run_id,
            user_id=current_user.id,
            reason=str(body.get("reason") or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return await get_flow_run_trace(db, run_id=run.id)


@router.post("/versions/{version_id}/partial-run")
async def post_partial_flow_run(
    version_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    project_id = str(body.get("project_id") or "").strip() or None
    try:
        await require_flow_start_workspace(db, current_user.id, project_id)
    except WorkflowRunError as error:
        raise _http(error) from None
    try:
        result = await run_partial_flow_version(
            db,
            version_id=version_id,
            node_id=str(body.get("node_id") or "").strip(),
            project_id=project_id,
            initial_input=body.get("initial_input") if isinstance(body.get("initial_input"), dict) else {},
            current_user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return await get_flow_run_trace(db, run_id=result["run_id"])
