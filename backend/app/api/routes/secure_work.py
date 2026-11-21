from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.secure_work import (
    get_work_item_coding_observability,
    get_work_item_lifecycle,
    list_coding_session_candidates,
    list_work_items,
    require_work_operator,
    require_work_reader,
)
from ...services.secure_work.access import work_scope_project_ids
from ...services.secure_work.work_item_listing import LIST_DEFAULT_LIMIT, LIST_MAX_LIMIT
from ._secure_work_scope import require_secure_work_scope
from .secure_work_coding_evidence import router as coding_evidence_router
from .secure_work_coding_pipelines import router as coding_pipelines_router
from .secure_work_plan_answers import router as plan_answers_router
from .secure_work_planning import router as planning_router

# Every route is bound to the caller's Workspaces before its handler runs.
router = APIRouter(
    prefix="/api/v1/secure-work", tags=["secure-work"], dependencies=[Depends(require_secure_work_scope)]
)
router.include_router(plan_answers_router)


@router.get("/coding-sessions")
async def get_coding_session_candidates(
    project_id: str | None = None,
    limit: int = Query(1000, ge=1, le=5000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    scope = await work_scope_project_ids(db, current_user)
    # One Workspace when the page names one: a Workspace outside the caller's scope lists nothing.
    wanted = (project_id or "").strip() or None
    if wanted:
        scope = {wanted} if scope is None or wanted in scope else set()
    return await list_coding_session_candidates(db, project_scope=scope, limit=limit)


@router.get("/work-items")
async def get_work_items(
    project_id: str | None = None,
    sync_config_id: str | None = None,
    source_status: str | None = None,
    work_state: str | None = None,
    sync_state: str | None = None,
    assignee: list[str] = Query(default=[]),
    label: list[str] = Query(default=[]),
    fix_version: list[str] = Query(default=[]),
    sprint_id: list[str] = Query(default=[]),
    sprint_name: list[str] = Query(default=[]),
    limit: int = Query(default=LIST_DEFAULT_LIMIT, ge=1, le=LIST_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    # The open task list (phone): only unfinished items, only mine, a search, counts per state.
    open: bool = False,  # noqa: A002 - the query parameter's name
    mine: bool = False,
    q: str | None = Query(default=None, max_length=100),
    state_counts: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_reader(db, current_user)
    identifiers = None
    if mine:
        from ...services.linked_accounts.resolution import account_identifiers  # noqa: PLC0415

        identifiers = {current_user.username, current_user.email, *await account_identifiers(db, current_user.id)}
    return await list_work_items(
        db,
        project_id=(project_id or "").strip() or None,
        sync_config_id=(sync_config_id or "").strip() or None,
        source_status=(source_status or "").strip() or None,
        work_state=(work_state or "").strip() or None,
        sync_state=(sync_state or "").strip() or None,
        assignees=assignee,
        labels=label,
        fix_versions=fix_version,
        sprint_ids=sprint_id,
        sprint_names=sprint_name,
        limit=limit,
        offset=offset,
        project_scope=await work_scope_project_ids(db, current_user),
        open_only=open,
        assignee_identifiers=identifiers,
        search=q,
        with_state_counts=state_counts,
    )


@router.get("/work-items/{work_item_id}/lifecycle")
async def get_work_item_lifecycle_route(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_reader(db, current_user)
    return await get_work_item_lifecycle(db, work_item_id)


@router.get("/work-items/{work_item_id}/coding-observability")
async def get_work_item_coding_observability_route(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    return await get_work_item_coding_observability(db, work_item_id)


# Included after the routes above so the registration order stays the same.
router.include_router(coding_pipelines_router)
router.include_router(coding_evidence_router)
router.include_router(planning_router)
