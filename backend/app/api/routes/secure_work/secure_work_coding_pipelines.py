"""Workflow transitions and coding pipelines of Work items. Included into ``secure_work.py``'s router, so its Workspace
scope dependency applies here too."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.secure_work import (
    control_coding_pipeline_run,
    create_coding_pipeline_config,
    dry_run_work_item_transition,
    get_coding_pipeline_trace,
    list_coding_pipeline_configs,
    list_work_item_state_events,
    require_work_operator,
    require_work_reader,
    start_coding_pipeline_run,
    start_work_item_coding_agent_execution,
    transition_work_item,
    update_coding_pipeline_config,
    update_coding_pipeline_stage,
)
from ....services.secure_work.access import work_scope_project_ids

router = APIRouter()


@router.post("/workflows/{workflow_id}/dry-run-transition")
async def post_workflow_transition_dry_run(
    workflow_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await dry_run_work_item_transition(
        db,
        workflow_id=workflow_id,
        work_item_id=str(payload.get("work_item_id") or ""),
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result


@router.get("/coding-pipelines")
async def get_coding_pipelines(
    project_id: str | None = None,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    return {
        "items": await list_coding_pipeline_configs(
            db,
            project_id=(project_id or "").strip() or None,
            include_inactive=include_inactive,
            project_scope=await work_scope_project_ids(db, current_user),
            viewer_id=current_user.id,
        )
    }


@router.post("/coding-pipelines")
async def post_coding_pipeline(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await create_coding_pipeline_config(db, current_user=current_user, payload=payload)
    await db.commit()
    return result


@router.put("/coding-pipelines/{config_id}")
async def put_coding_pipeline(
    config_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await update_coding_pipeline_config(db, config_id=config_id, current_user=current_user, payload=payload)
    await db.commit()
    return result


@router.post("/work-items/{work_item_id}/transition")
async def post_work_item_transition(
    work_item_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await transition_work_item(
        db,
        workflow_id=str(payload.get("workflow_id") or ""),
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result


@router.get("/work-items/{work_item_id}/state-events")
async def get_work_item_state_events(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_reader(db, current_user)
    return {"items": await list_work_item_state_events(db, work_item_id)}


@router.get("/work-items/{work_item_id}/coding-pipeline")
async def get_work_item_coding_pipeline(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    return await get_coding_pipeline_trace(db, work_item_id)


@router.post("/work-items/{work_item_id}/coding-pipeline/start")
async def post_work_item_coding_pipeline_start(
    work_item_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await start_coding_pipeline_run(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload or {},
    )
    await db.commit()
    return result


@router.post("/work-items/{work_item_id}/coding-agent/start")
async def post_work_item_coding_agent_start(
    work_item_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await start_work_item_coding_agent_execution(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload or {},
    )
    await db.commit()
    return result


@router.post("/coding-pipeline-runs/{run_id}/control")
async def post_coding_pipeline_control(
    run_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await control_coding_pipeline_run(db, run_id=run_id, current_user=current_user, payload=payload)
    await db.commit()
    return result


@router.put("/coding-pipeline-runs/{run_id}/stages/{stage_id}")
async def put_coding_pipeline_stage(
    run_id: str,
    stage_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await update_coding_pipeline_stage(
        db,
        run_id=run_id,
        stage_id=stage_id,
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result
