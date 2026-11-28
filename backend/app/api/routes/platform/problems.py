"""Problems: list and acknowledge what needs an admin's attention."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.problems.acknowledgements import MAX_KEY_LENGTH
from ....services.problems.scope import ProblemsAccessError, admin_scope, workspace_scope
from ....services.problems.service import ProblemsQueryError, acknowledge_problem, list_problems

admin_router = APIRouter(prefix="/api/v1/admin/problems", tags=["problems"])
workspace_router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/problems", tags=["problems"])


def _refusal(error: ProblemsAccessError | ProblemsQueryError) -> HTTPException:
    if isinstance(error, ProblemsQueryError):
        return HTTPException(status_code=422, detail={"code": error.code, "message": error.message,
                                                      "field": error.field})
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


@admin_router.get("")
async def get_admin_problems(
    workspace_id: str | None = Query(None, max_length=64),
    kind: str | None = Query(None, max_length=40),
    severity: str | None = Query(None, max_length=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        scope = await admin_scope(db, user, workspace_id or None)
        return await list_problems(db, user, scope, kind=kind, severity=severity)
    except (ProblemsAccessError, ProblemsQueryError) as error:
        raise _refusal(error) from None


@admin_router.post("/{key:path}/acknowledge")
async def post_acknowledge_problem(
    key: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        scope = await admin_scope(db, user, None)
    except ProblemsAccessError as error:
        raise _refusal(error) from None
    problem = await acknowledge_problem(db, user, scope, key) if 0 < len(key) <= MAX_KEY_LENGTH else None
    if problem is None:
        raise HTTPException(status_code=404, detail={"code": "problem_not_found",
                                                     "message": "There is no such open problem to acknowledge."})
    await db.commit()
    return {"key": problem.key, "acknowledged": True}


@workspace_router.get("")
async def get_workspace_problems(
    workspace_id: str,
    kind: str | None = Query(None, max_length=40),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        scope = await workspace_scope(db, user, workspace_id)
        return await list_problems(db, user, scope, kind=kind)
    except (ProblemsAccessError, ProblemsQueryError) as error:
        raise _refusal(error) from None


__all__ = ["admin_router", "workspace_router"]
