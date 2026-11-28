"""``/api/v1/workflow-runs``: start, read, list and bind workflow runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User, WorkflowRun
from ....services.auth import get_current_user
from ....services.project.private_workspace import outside_foreign_private, refuse_foreign_private
from ....services.secure_work.access import work_scope_project_ids
from ....services.workflow_runs.access import require_start_scope
from ....services.workflow_runs.records import WorkflowRunError, new_chat_session, start_run
from ....services.workflow_runs.run_engine import run_engine_routes
from ....services.workflow_runs.run_lists import work_extras
from ....services.workflow_runs.run_start import start_work_item
from ....services.workflow_runs.views import run_row
from ..identity.token_profile import router as token_profile_router
from ._workflow_run_http import StartRunRequest, _http, _own_session, _start_context, _view
from .spec_studio import router as spec_studio_router
from .workflow_audience_proof import router as audience_proof_router
from .workflow_run_detail import router as run_detail_router
from .workflow_run_settings import router as run_settings_router

router = APIRouter(prefix="/api/v1/workflow-runs", tags=["workflow-runs"])
MAX_LIST = 200


@router.post("")
async def create_run(
    body: StartRunRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    try:
        # Resolve first: nothing (not even the run's chat session) is written for an unknown or foreign item, a missing
        # or unknown Workspace (typed ``needs_configuration`` / ``workspace_required``) or a foreign Workspace.
        item = await start_work_item(db, body.work_item_id)
        scope = body.project_id or (item.project_id if item is not None else None)
        await require_start_scope(db, current_user, project_id=scope, item=item)
        if body.session_id:
            session = await _own_session(db, body.session_id, current_user)
        else:
            # The run starts in a new chat session of its own, in the run's Workspace (it exists before the first
            # phase).
            session = await new_chat_session(db, current_user, scope)
        run = await start_run(
            db, user=current_user, workflow_key=body.workflow_key, project_id=body.project_id,
            work_item_id=body.work_item_id, repository=body.repository, branch=body.branch, session=session,
            runtime_target=body.runtime_target,
            context=_start_context(body),
        )
    except WorkflowRunError as error:
        raise _http(error) from error
    await db.commit()
    return {"run": await _view(db, run, current_user), "session_id": session.id}


async def _runs_query(
    db: AsyncSession, user: User, *, status: str | None, work_item_id: str | None, project_id: str | None,
    repository_id: str | None,
):
    query = select(WorkflowRun)
    if repository_id:
        # Work › Repositories: the runs of one repository record. A run names its repository
        # as "<provider>:<owner>/<repo>"; the record's name is matched the way the SCM actions match it.
        from app.services.workflow_runs.platform.repo_ref import record_path

        from ....models import CodeRepository

        record = await db.get(CodeRepository, repository_id)
        if record is None or await refuse_foreign_private(db, record.project_id, user.id):
            raise HTTPException(status_code=404, detail={"code": "repository_not_found",
                                                         "message": "This repository record does not exist."})
        query = query.where(WorkflowRun.project_id == record.project_id,
                            func.lower(WorkflowRun.repository).endswith(":" + record_path(record.name),
                                                                         autoescape=True))
    scope = await work_scope_project_ids(db, user)
    query = query.where(outside_foreign_private(WorkflowRun.project_id, user.id))
    if scope is not None:
        query = query.where(or_(WorkflowRun.requested_by == user.id, WorkflowRun.project_id.in_(scope)))
    if status == "attention":
        # The runs that need a person: paused, or waiting for a decision or an external state.
        query = query.where(WorkflowRun.status.in_(("paused", "waiting")))
    elif status:
        query = query.where(WorkflowRun.status == status)
    if work_item_id:
        query = query.where(WorkflowRun.work_item_id == work_item_id)
    if project_id:
        query = query.where(WorkflowRun.project_id == project_id)
    return query


@router.get("")
async def list_runs(
    status: str | None = Query(default=None, max_length=20),
    work_item_id: str | None = Query(default=None, max_length=36),
    project_id: str | None = Query(default=None, max_length=36),
    view: str | None = Query(default=None, max_length=10),
    repository_id: str | None = Query(default=None, max_length=36),
    limit: int | None = Query(default=None, ge=1, le=MAX_LIST),
    before: str | None = Query(default=None, max_length=40),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = await _runs_query(db, current_user, status=status, work_item_id=work_item_id, project_id=project_id,
                              repository_id=repository_id)
    from ....services.workflow_runs.run_list import (
        before_filter,
        light_query,
        light_runs,
        main_sessions,
        responsible_views,
        workflow_titles,
    )

    # Never the runs' big JSON in a list, one query per kind, pages by cursor.
    size = min(limit or MAX_LIST, MAX_LIST)
    query = light_query(before_filter(query, before)).order_by(WorkflowRun.updated_at.desc())
    rows = light_runs(list((await db.execute(query.limit(size))).all()))
    # ``view=work``: Work › Runs also shows each run's step, pause, pull request and cost.
    extras = await work_extras(db, rows) if view == "work" else {}
    # Each run's coding engine and route (own subscription or company model) for the phone's run line.
    ids = [run.id for run in rows]
    engines, sessions, responsible = (await run_engine_routes(db, ids), await main_sessions(db, ids),
                                      await responsible_views(db, rows))
    titles = await workflow_titles(db, rows)
    return {"runs": [{**run_row(run), **extras.get(run.id, {}), **engines[run.id],
                      "session_id": sessions.get(run.id), "responsible": responsible[run.id],
                      "workflow_title": titles.get(run.id)} for run in rows],
            "next_before": rows[-1].updated_at.isoformat() if len(rows) == size and rows else None}


# Included after the routes above so the registration order stays the same.
router.include_router(run_settings_router)
router.include_router(run_detail_router)
router.include_router(audience_proof_router)
router.include_router(spec_studio_router)
router.include_router(token_profile_router)
