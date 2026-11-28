"""CI/CD traces and findings, change units, code review events, coding audit and quality gates. Included into
``secure_work.py``'s router, so its Workspace scope dependency applies here too."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.secure_work import (
    create_coding_audit_event,
    create_coding_review_event,
    evaluate_coding_quality_gates,
    get_agent_feedback_context,
    get_coding_audit_report,
    list_coding_review_events,
    list_repository_profiles,
    list_work_item_change_units,
    list_work_item_cicd_findings,
    list_work_item_cicd_pipeline_traces,
    record_work_item_cicd_finding,
    record_work_item_cicd_pipeline_trace,
    require_work_operator,
    require_work_reader,
)
from ....services.secure_work.access import get_scoped_work_item, work_scope_project_ids

router = APIRouter()


@router.get("/work-items/{work_item_id}/cicd-pipeline-traces")
async def get_work_item_cicd_pipeline_traces(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    return await list_work_item_cicd_pipeline_traces(db, work_item_id)


@router.post("/work-items/{work_item_id}/cicd-pipeline-traces")
async def post_work_item_cicd_pipeline_trace(
    work_item_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await record_work_item_cicd_pipeline_trace(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result


@router.get("/work-items/{work_item_id}/cicd-findings")
async def get_work_item_cicd_findings(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    return await list_work_item_cicd_findings(db, work_item_id)


@router.post("/work-items/{work_item_id}/cicd-findings")
async def post_work_item_cicd_finding(
    work_item_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await record_work_item_cicd_finding(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result


@router.get("/repository-profiles")
async def get_repository_profiles(
    project_id: str | None = None,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    return {
        "items": await list_repository_profiles(
            db,
            project_id=(project_id or "").strip() or None,
            include_inactive=include_inactive,
            project_scope=await work_scope_project_ids(db, current_user),
            viewer_id=current_user.id,
        )
    }


@router.get("/work-items/{work_item_id}/change-units")
async def get_work_item_change_units(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_reader(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    return {"items": await list_work_item_change_units(db, work_item_id)}


@router.get("/work-items/{work_item_id}/coding-review-events")
async def get_work_item_coding_review_events(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    return await list_coding_review_events(db, work_item_id)


@router.post("/work-items/{work_item_id}/coding-review-events")
async def post_work_item_coding_review_event(
    work_item_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    result = await create_coding_review_event(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result


@router.get("/work-items/{work_item_id}/agent-feedback-context")
async def get_work_item_agent_feedback_context(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    return await get_agent_feedback_context(db, work_item_id)


@router.get("/work-items/{work_item_id}/coding-audit")
async def get_work_item_coding_audit(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    return await get_coding_audit_report(db, work_item_id)


@router.post("/work-items/{work_item_id}/coding-audit/events")
async def post_work_item_coding_audit_event(
    work_item_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    result = await create_coding_audit_event(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result


@router.post("/work-items/{work_item_id}/coding-quality-gates/evaluate")
async def post_work_item_coding_quality_gates(
    work_item_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    result = await evaluate_coding_quality_gates(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload or {},
    )
    await db.commit()
    return result
