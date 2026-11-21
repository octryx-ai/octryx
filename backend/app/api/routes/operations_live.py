"""Operations › Live. Transport only; the logic is ``services/operations``.

- ``GET /api/v1/admin/operations/live?workspace_id=`` — platform admins: everything; Workspace admins and owners:
  the Workspaces they administer; others 403 ``admin_required``.
- ``GET /api/v1/workspaces/{workspace_id}/operations/live`` — members of that Workspace (404 otherwise).
- ``GET /api/v1/admin/operations/costs?workspace_id=&days=7&group=workflow|work_item|run|person|workspace`` —
  cost and outcome of the runs started in the window (gap #4); admins in the Problems scope.
- ``GET /api/v1/admin/operations/seat-usage?workspace_id=&days=30`` — per person, what their seat calls would have
  cost through the API at list price, beside their real API cost; admins in the Problems scope.
- Emergency stop (gap #3; only on this explicit request, audited in ``kill_switch_logs``):
  ``GET /api/v1/admin/operations/emergency-stop/preview?workspace_id=`` (what a stop would touch),
  ``POST /api/v1/admin/operations/emergency-stop`` ``{workspace_id?, reason}`` and
  ``GET /api/v1/admin/operations/emergency-stop/history?workspace_id=``. Without ``workspace_id`` it is the whole
  platform (platform admins only); with one, platform admins and that Workspace's admins and owners.

Errors ``{detail: {code, message}}`` as in the Problems API.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import require_visible_workspace
from ...services.auth import get_current_user
from ...services.operations import emergency_stop
from ...services.operations.costs import CostQueryError, cost_report
from ...services.operations.live import live_view
from ...services.operations.seat_usage import seat_usage_report
from ...services.problems.model import CollectContext
from ...services.problems.scope import ProblemsAccessError, admin_scope, workspace_scope
from ...time_utils import utc_now

admin_router = APIRouter(prefix="/api/v1/admin/operations", tags=["operations"])
workspace_router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/operations", tags=["operations"])


def _refusal(error: ProblemsAccessError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


@admin_router.get("/live")
async def get_admin_live(
    workspace_id: str | None = Query(None, max_length=64),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        scope = await admin_scope(db, user, workspace_id or None)
    except ProblemsAccessError as error:
        raise _refusal(error) from None
    return await live_view(db, user, scope)


@workspace_router.get("/live")
async def get_workspace_live(
    workspace_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        scope = await workspace_scope(db, user, workspace_id)
    except ProblemsAccessError as error:
        raise _refusal(error) from None
    return await live_view(db, user, scope)


@admin_router.get("/costs")
async def get_costs(
    workspace_id: str | None = Query(None, max_length=64),
    days: int = Query(7),
    group: str = Query("workflow", max_length=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        scope = await admin_scope(db, user, workspace_id or None)
    except ProblemsAccessError as error:
        raise _refusal(error) from None
    now = utc_now()
    try:
        return await cost_report(db, scope=CollectContext(now=now, workspace_ids=scope.workspace_ids).scope, now=now,
                                 days=days, group=group)
    except CostQueryError as error:
        raise HTTPException(status_code=422, detail={"code": "invalid_filter", "field": error.field,
                                                     "message": error.message}) from None


@admin_router.get("/seat-usage")
async def get_seat_usage(
    workspace_id: str | None = Query(None, max_length=64),
    days: int = Query(30),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        scope = await admin_scope(db, user, workspace_id or None)
    except ProblemsAccessError as error:
        raise _refusal(error) from None
    now = utc_now()
    try:
        return await seat_usage_report(db, scope=CollectContext(now=now, workspace_ids=scope.workspace_ids).scope,
                                       now=now, days=days)
    except CostQueryError as error:
        raise HTTPException(status_code=422, detail={"code": "invalid_filter", "field": error.field,
                                                     "message": error.message}) from None


async def _stop_scope(db: AsyncSession, user: User, workspace_id: str | None) -> str | None:
    """The Workspace to stop (``None`` = platform); refuses who may not stop it. A named Workspace that does not exist
    or that the caller is no member of is 404 ``project_not_found`` first, for every caller (a platform admin
    included), so the admin branch never acts on an unresolved id and a refusal never reveals a foreign one."""
    await require_visible_workspace(db, user.id, workspace_id or None)
    try:
        scope = await admin_scope(db, user, workspace_id or None)
    except ProblemsAccessError as error:
        raise _refusal(error) from None
    if workspace_id:
        if scope.workspace_ids is not None and workspace_id not in scope.workspace_ids:
            raise HTTPException(status_code=403, detail={"code": "workspace_admin_required",
                                                         "message": "Only this Workspace's admins can stop it."})
        return workspace_id
    if scope.workspace_ids is not None:
        raise HTTPException(status_code=403, detail={"code": "platform_admin_required",
                                                     "message": "Only platform admins can stop the whole platform."})
    return None


@admin_router.get("/emergency-stop/preview")
async def get_emergency_stop_preview(
    workspace_id: str | None = Query(None, max_length=64),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await emergency_stop.preview(db, await _stop_scope(db, user, workspace_id))


@admin_router.post("/emergency-stop")
async def post_emergency_stop(
    body: dict[str, Any] = Body(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    workspace_id = body.get("workspace_id")
    if workspace_id is not None and not isinstance(workspace_id, str):
        raise HTTPException(status_code=422, detail={"code": "workspace_id_invalid", "message": "workspace_id"})
    target = await _stop_scope(db, user, workspace_id or None)
    try:
        result = await emergency_stop.stop(db, user, target, str(body.get("reason") or ""))
    except emergency_stop.EmergencyStopError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message}) from None
    await db.commit()
    return result


@admin_router.post("/emergency-stop/resume")
async def post_emergency_stop_resume(
    body: dict[str, Any] = Body(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Let new starts run again in exactly this scope; paused runs are continued one by one."""
    workspace_id = body.get("workspace_id")
    if workspace_id is not None and not isinstance(workspace_id, str):
        raise HTTPException(status_code=422, detail={"code": "workspace_id_invalid", "message": "workspace_id"})
    target = await _stop_scope(db, user, workspace_id or None)
    try:
        return await emergency_stop.resume_new_starts(db, user, target, str(body.get("reason") or ""))
    except emergency_stop.EmergencyStopError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message}) from None


@admin_router.get("/emergency-stop/history")
async def get_emergency_stop_history(
    workspace_id: str | None = Query(None, max_length=64),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"stops": await emergency_stop.history(db, await _stop_scope(db, user, workspace_id))}


__all__ = ["admin_router", "workspace_router"]
