"""Handing a workflow run over, and the admin emergency stop (Octryx companion, "watch, team and handovers").

- ``POST /api/v1/workflow-runs/{id}/handover-requests`` ``{to_user_id, reason}``: the requester (or an admin);
- ``POST /api/v1/workflow-runs/{id}/handover/accept`` and ``/handover/decline`` ``{reason?}``: only the receiver;
- ``POST /api/v1/workflow-runs/{id}/emergency-stop`` ``{reason}``: platform admins only; aborts the run, stops its
  device turn and writes an audit row with the reason.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import AuditLog, User, WorkflowRun
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.auth import get_current_user
from ...services.observability.run_quality_metrics import intervention
from ...services.workflow_runs.records import WorkflowRunError
from ...services.workflow_runs.run_handover import accept_handover, decline_handover, request_handover

router = APIRouter(prefix="/api/v1/workflow-runs", tags=["workflow-runs"])


class HandoverRequest(BaseModel):
    to_user_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=500)


class ReasonBody(BaseModel):
    reason: str = Field(default="", max_length=500)


def _http(error: WorkflowRunError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": str(error)})


async def _run(db: AsyncSession, run_id: str) -> WorkflowRun:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_run", "message": "Unknown run."})
    return run


@router.post("/{run_id}/handover-requests")
async def post_handover_request(run_id: str, body: HandoverRequest, current_user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    run = await _run(db, run_id)
    try:
        value = await request_handover(db, run, user=current_user, to_user_id=body.to_user_id, reason=body.reason)
    except WorkflowRunError as error:
        raise _http(error) from error
    intervention(db, run, "handover_request")
    await db.commit()
    return {"handover": value}


@router.post("/{run_id}/handover/accept")
async def post_handover_accept(run_id: str, current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    run = await _run(db, run_id)
    try:
        value = await accept_handover(db, run, user=current_user)
    except WorkflowRunError as error:
        if error.persist:  # the refusal's run event (``server_build_refused``) is kept
            await db.commit()
        raise _http(error) from error
    intervention(db, run, "handover_accept")
    await db.commit()
    return {"handover": value, "session_id": value.get("session_id")}


@router.post("/{run_id}/handover/decline")
async def post_handover_decline(run_id: str, body: ReasonBody, current_user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    run = await _run(db, run_id)
    try:
        await decline_handover(db, run, user=current_user, reason=body.reason)
    except WorkflowRunError as error:
        raise _http(error) from error
    intervention(db, run, "handover_decline")
    await db.commit()
    return {"declined": run_id}


@router.post("/{run_id}/emergency-stop")
async def post_emergency_stop(run_id: str, body: ReasonBody, current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    from ...services.workflow_runs.pause import abort_run

    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail={"code": "admin_only", "message": "Only an admin stops a run."})
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail={"code": "reason_required", "message": "Say why."})
    run = await _run(db, run_id)
    try:
        await abort_run(db, run, user=current_user, reason=f"Emergency stop: {reason}")
    except WorkflowRunError as error:
        raise _http(error) from error
    db.add(AuditLog(user_id=current_user.id, action="workflow_run.emergency_stop", resource_type="workflow_run",
                    resource_id=run.id, details={"run_id": run.id, "requested_by": run.requested_by,
                                                 "reason": reason}))
    intervention(db, run, "emergency_stop")
    await db.commit()
    return {"stopped": run.id}
