"""Workflow checks: recent results per workflow."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.notification_delivery import require_admin_user
from ....services.workflow_checks.library import CHECK_TYPES
from ....services.workflow_checks.results import MAX_LISTED, list_check_results

router = APIRouter(prefix="/api/v1/workflow-checks", tags=["workflow-checks"])


@router.get("/results")
async def get_check_results(
    workflow_key: str | None = None,
    session_id: str | None = None,
    runtime: str | None = None,
    limit: int = Query(50, ge=1, le=MAX_LISTED),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    results = await list_check_results(
        db, workflow_key=(workflow_key or "").strip() or None, session_id=(session_id or "").strip() or None,
        runtime=(runtime or "").strip() or None, limit=limit,
    )
    return {"results": results, "check_types": list(CHECK_TYPES)}
