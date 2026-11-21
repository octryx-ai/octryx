from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Approval, User
from ...schemas.operations.approval import (
    ApprovalDecision,
    ApprovalMetadataResponse,
    ApprovalResponse,
    WorkflowStartOutcome,
)
from ...services.approval.access import (
    APPROVAL_NOT_FOUND_DETAIL,
    approval_visibility_clause,
    decide_sessionless_approval,
)
from ...services.approval.decidable import decidable_approvals
from ...services.approval.detail import approval_detail
from ...services.auth import get_current_user
from ...services.session.approval_decision import decide_session_approval
from ...services.standing_approvals.decision import decide_approval_always

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])

# The phone's list: the newest decidable approvals.
DECIDABLE_LIST_SIZE = 100


@router.get("", response_model=list[ApprovalResponse])
async def list_approvals(
    status: str | None = "pending",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Approval)
    visible = await approval_visibility_clause(db, current_user.id)
    if visible is not None:  # everyone but a global admin sees only their sessions' and runs' approvals
        query = query.where(visible)
    if status:
        query = query.where(Approval.status == status)
    query = query.order_by(Approval.created_at.desc()).limit(50)
    result = await db.execute(query)
    approvals = result.scalars().all()
    return [
        ApprovalResponse(
            id=a.id,
            task_run_id=a.task_run_id,
            session_id=a.session_id,
            requested_by=a.requested_by,
            approved_by=a.approved_by,
            action=a.action,
            status=a.status,
            reason=a.reason,
            decision_note=a.decision_note,
            created_at=a.created_at.isoformat(),
            resolved_at=a.resolved_at.isoformat() if a.resolved_at else None,
        )
        for a in approvals
    ]


@router.get("/decidable")
async def list_decidable_approvals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The pending approvals this person may decide, each with its masked preview and ``offered_decisions``.

    For the phone (approvals also on the go): the list a person works through, then
    ``POST /{id}/approve`` or ``/reject``. Each item passes the same decision check the decision itself runs, so
    nothing is listed that the person could not decide. "Always" stays in the web. The circle is
    ``services/approval/decidable`` - the same one the attention queue pushes to the phone.
    """
    items = []
    for approval in await decidable_approvals(db, current_user, limit=DECIDABLE_LIST_SIZE):
        detail = await approval_detail(db, approval)
        items.append({**detail, "id": approval.id, "action": approval.action, "status": approval.status,
                      "session_id": approval.session_id, "task_run_id": approval.task_run_id,
                      "requested_by": approval.requested_by,
                      "created_at": approval.created_at.isoformat() if approval.created_at else None})
    return {"items": items, "count": len(items)}


@router.get("/{approval_id}", response_model=ApprovalMetadataResponse)
async def get_approval(
    approval_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One approval with its detail (masked change preview, offered decisions, decider, run), under the list's
    visibility rule; the free-text ``reason`` stays out (the preview's own summary says what is asked).

    The scope is exactly ``services/approval/access.approval_visibility_clause``, so the list
    and the lookup by id always agree; out of scope and unknown are the same 404.
    """
    query = select(Approval).where(Approval.id == approval_id)
    visible = await approval_visibility_clause(db, current_user.id)
    if visible is not None:
        query = query.where(visible)
    approval = (await db.execute(query)).scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail=APPROVAL_NOT_FOUND_DETAIL)
    detail = await approval_detail(db, approval)
    return ApprovalMetadataResponse(
        **detail,
        id=approval.id,
        kind="session" if approval.session_id else "task_run" if approval.task_run_id else "governance",
        status=approval.status,
        action=approval.action,
        session_id=approval.session_id,
        task_run_id=approval.task_run_id,
        requested_by=approval.requested_by,
        approved_by=approval.approved_by,
        created_at=approval.created_at.isoformat() if approval.created_at else None,
        resolved_at=approval.resolved_at.isoformat() if approval.resolved_at else None,
    )


async def _decided_response(db: AsyncSession, approval: Approval) -> ApprovalResponse:
    """A decided session approval with the outcome of the workflow start it resumed, if it resumed one."""
    from ...models import Session as AgentSession
    from ...services.workflow_routing.proposal_approval import workflow_start_outcome

    session = await db.get(AgentSession, approval.session_id, populate_existing=True) if approval.session_id else None
    outcome = workflow_start_outcome(session, approval)
    return _response(approval, workflow_start=WorkflowStartOutcome(**outcome) if outcome else None)


def _response(approval: Approval, *, workflow_start: WorkflowStartOutcome | None = None) -> ApprovalResponse:
    return ApprovalResponse(
        id=approval.id,
        task_run_id=approval.task_run_id,
        session_id=approval.session_id,
        requested_by=approval.requested_by,
        approved_by=approval.approved_by,
        action=approval.action,
        status=approval.status,
        reason=approval.reason,
        decision_note=approval.decision_note,
        created_at=approval.created_at.isoformat(),
        resolved_at=approval.resolved_at.isoformat() if approval.resolved_at else None,
        workflow_start=workflow_start,
    )


async def _decide(db: AsyncSession, *, approval_id: str, user: User, decision: str, reason: str | None):
    result = await db.execute(select(Approval).where(Approval.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.session_id:
        # A session approval is decided and resumed by the one owner every route shares.
        return await _decided_response(db, await decide_session_approval(
            db, approval_id=approval_id, decider_id=user.id, decision=decision, reason=reason))
    # A task-run approval (no session): its owner, starter, a writer of its run's session, or an admin.
    return _response(
        await decide_sessionless_approval(db, approval=approval, decider_id=user.id, decision=decision, reason=reason)
    )


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve(
    approval_id: str,
    body: ApprovalDecision,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _decide(db, approval_id=approval_id, user=current_user, decision="approved", reason=body.reason)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject(
    approval_id: str,
    body: ApprovalDecision,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _decide(db, approval_id=approval_id, user=current_user, decision="rejected", reason=body.reason)


@router.post("/{approval_id}/always", response_model=ApprovalResponse)
async def always(
    approval_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Always for this Workspace on a session approval: the standing rule, then the same approval."""
    return await _decided_response(
        db, await decide_approval_always(db, approval_id=approval_id, decider_id=current_user.id))
