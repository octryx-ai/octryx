"""Work item analysis REST."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Project, User, WorkItemAnalysis
from ....services.access_control import get_project_role_for_user
from ....services.auth import get_current_user
from ....services.secure_work.access import get_scoped_work_item, require_work_operator
from ....services.work_item_analysis.reporter_questions import post_proposed_questions
from ....services.work_item_analysis.runner import CONTENT_IS_DATA, MODE_MANUAL, analyze_work_item, list_analyses
from ....services.work_item_analysis.settings import AnalysisSettingsError, set_analysis_settings, settings_from_config
from ..secure_work._secure_work_scope import require_secure_work_scope

router = APIRouter(tags=["work-item-analysis"])
items_router = APIRouter(
    prefix="/api/v1/secure-work", tags=["work-item-analysis"], dependencies=[Depends(require_secure_work_scope)]
)
SETTINGS_PATH = "/api/v1/secure-work/work-item-analysis-settings/{project_id}"


@items_router.post("/work-items/{work_item_id}/analyze")
async def post_work_item_analyze(
    work_item_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await require_work_operator(db, current_user)
    item = await get_scoped_work_item(db, current_user, work_item_id)
    return await analyze_work_item(db, item=item, user=current_user, mode=MODE_MANUAL)


@items_router.get("/work-items/{work_item_id}/analysis")
async def get_work_item_latest_analysis(
    work_item_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await require_work_operator(db, current_user)
    item = await get_scoped_work_item(db, current_user, work_item_id)
    latest = await list_analyses(db, item.id, limit=1)
    if not latest:
        return {"work_item_id": item.id, "status": "none", "analysis": None, "content_is_data": CONTENT_IS_DATA}
    return latest[0]


@items_router.get("/work-items/{work_item_id}/analyses")
async def get_work_item_analyses(
    work_item_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await require_work_operator(db, current_user)
    item = await get_scoped_work_item(db, current_user, work_item_id)
    return {"items": await list_analyses(db, item.id)}


@items_router.post("/work-items/{work_item_id}/analyses/{analysis_id}/ask-reporter")
async def post_work_item_analysis_ask_reporter(
    work_item_id: str, analysis_id: str, current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_work_operator(db, current_user)
    item = await get_scoped_work_item(db, current_user, work_item_id)
    analysis = await db.get(WorkItemAnalysis, analysis_id)
    if analysis is None or analysis.work_item_id != item.id:
        raise HTTPException(status_code=404, detail={"code": "analysis_not_found"})
    project = await db.get(Project, item.project_id)
    settings, _source = settings_from_config(project.config if project is not None else None)
    result = await post_proposed_questions(db, item=item, analysis=analysis, ask=settings.ask_reporter,
                                           person_id=current_user.id)
    # Only a comment that reached Jira moves the analysis on; "not sent" (asking switched off, Jira refused or
    # unreachable) leaves it proposed, so a person can send it again later.
    if result.get("state") == "posted":
        analysis.reporter_question = result
    await db.commit()
    return {"work_item_id": item.id, "analysis_id": analysis.id, "sent": result.get("state") == "posted",
            "attempt": result, "reporter_question": analysis.reporter_question}


async def _workspace(db: AsyncSession, user: User, project_id: str, *, write: bool) -> tuple[Project, bool]:
    role = await get_project_role_for_user(db, user.id, project_id)
    project = await db.get(Project, project_id) if role is not None else None
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    can_edit = role in {"admin", "owner"}
    if write and not can_edit:
        raise HTTPException(status_code=403, detail="Workspace admin or owner role required")
    return project, can_edit


def _payload(project: Project, can_edit: bool) -> dict[str, Any]:
    settings, source = settings_from_config(project.config)
    return {"project_id": project.id, **settings.as_dict(), "source": source, "can_edit": can_edit}


@router.get(SETTINGS_PATH)
async def get_analysis_settings(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=False)
    return _payload(project, can_edit)


@router.put(SETTINGS_PATH)
async def put_analysis_settings(
    project_id: str,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=True)
    try:
        await set_analysis_settings(db, project=project, value=body, actor_id=current_user.id)
    except AnalysisSettingsError as error:
        raise HTTPException(status_code=422, detail={"errors": [{"code": error.code, "field": error.field}]}) from None
    await db.commit()
    await db.refresh(project)
    return _payload(project, can_edit)


__all__ = ["items_router", "router"]
