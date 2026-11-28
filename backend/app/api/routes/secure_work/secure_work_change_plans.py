"""Workspace-scoped Work plan reads: the cross-item Change Plan list and a full Work Item."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.secure_work.access import get_scoped_work_item, require_work_reader, work_scope_project_ids
from ....services.secure_work.plans.plan_listing import (
    CURSOR_MAX_LENGTH,
    PLAN_LIST_DEFAULT_LIMIT,
    PLAN_LIST_MAX_LIMIT,
    list_change_plan_summaries,
    resolve_plan_list_filters,
)
from ....services.secure_work.serializers import serialize_work_item

router = APIRouter(prefix="/api/v1/secure-work", tags=["secure-work"])

_PLAN_LIST_QUERY_KEYS = frozenset(
    {"queue", "status", "include_superseded", "project_id", "work_item_id", "limit", "cursor"}
)


@router.get("/change-plans")
async def get_change_plan_summaries(
    request: Request,
    queue: str | None = None,
    status: list[str] = Query(default=[]),
    include_superseded: bool | None = None,
    project_id: str | None = None,
    work_item_id: str | None = None,
    limit: int = Query(default=PLAN_LIST_DEFAULT_LIMIT, ge=1, le=PLAN_LIST_MAX_LIMIT),
    cursor: str | None = Query(default=None, max_length=CURSOR_MAX_LENGTH),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_reader(db, current_user)
    # An unknown filter (for example a misspelled "statuses") is refused instead of ignored.
    unknown = sorted(set(request.query_params.keys()) - _PLAN_LIST_QUERY_KEYS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown filter: {', '.join(unknown)}")
    filters = resolve_plan_list_filters(
        queue=queue,
        statuses=status,
        include_superseded=include_superseded,
        project_id=project_id,
        work_item_id=work_item_id,
        limit=limit,
        cursor=cursor,
    )
    scope = await work_scope_project_ids(db, current_user)
    return await list_change_plan_summaries(db, scope=scope, filters=filters)


@router.get("/work-items/{work_item_id}")
async def get_work_item(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The full serialized Work Item (same shape as a ``GET /work-items`` entry), scoped."""
    await require_work_reader(db, current_user)
    # The object boundary: 404 when missing, 403 outside the user's workspaces.
    from ....services.secure_work.work_item_close import close_preview

    item = await get_scoped_work_item(db, current_user, work_item_id)
    # The detail says up front whether Close writes to the source (the list rows stay lean).
    return {**serialize_work_item(item), **await close_preview(db, item)}
