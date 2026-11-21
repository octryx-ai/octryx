"""Approval resolution orchestration.

A decision is a compare-and-set on the approval row (``pending`` -> decided): of two
concurrent deciders (two routes, a route and the timeout sweeper, two sweeps) exactly
one wins, and only the winner applies the side effects and may resume the turn.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, Session
from ...time_utils import utc_now
from ..change_preview import acknowledge_change_previews_for_approval, approval_grants_from_preview
from ..decisions.approvals import record_approval_decided
from ..run_capability.chat_write_plan import activate_confirmed_plan
from ..session.run_state import RUN_STATUS_COMPLETED, RUN_STATUS_STOPPED, set_session_run_state
from ..team_notification import create_notification

# The closed status an approval gate's timeout decides (``turn_execution_summary.APPROVAL_STATUSES``).
APPROVAL_STATUS_EXPIRED = "expired"


REFUSAL_SELF_APPROVAL_NOT_ALLOWED = "self_approval_not_allowed"


async def _require_four_eyes(db: AsyncSession, approval: Approval, *, resolved_by: str | None, status: str) -> None:
    """A governance review (no session, no task run) is approved under the platform approval rule on every path.

    The admin Approvals page therefore cannot consume a review
    by its own requester under four-eyes. Rejecting and time limits are not approvals and are never refused here.
    """
    if status != "approved" or resolved_by is None or approval.session_id or approval.task_run_id:
        return
    from ..governance.four_eyes import FOUR_EYES_PASSING_STATUSES, decide_four_eyes

    decision = await decide_four_eyes(db, approval.requested_by, resolved_by)
    if decision.status not in FOUR_EYES_PASSING_STATUSES:
        raise HTTPException(status_code=409, detail={
            "code": REFUSAL_SELF_APPROVAL_NOT_ALLOWED,
            "message": "The approval rule is four-eyes: another admin has to approve this review.",
        })


async def resolve_approval_request(
    db: AsyncSession,
    *,
    approval_id: str,
    resolved_by: str,
    status: str,
    reason: str | None = None,
) -> Approval | None:
    """Decide a pending approval; returns the row, decided now or earlier (``None`` if unknown)."""
    decided = await decide_pending_approval(
        db, approval_id=approval_id, resolved_by=resolved_by, status=status, reason=reason
    )
    if decided is not None:
        return decided
    return (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one_or_none()


def _append_grants(session: Session, grants_to_add: list[dict]) -> None:
    metadata = dict(session.metadata_ or {})
    grants = list(metadata.get("approval_grants") or [])
    grants.extend(grants_to_add)
    metadata["approval_grants"] = grants
    session.metadata_ = metadata


async def _apply_approved(
    db: AsyncSession, session: Session, approval: Approval, *, resolved_by: str | None
) -> None:
    """An approved change preview becomes a session grant, a confirmed write plan the request's plan."""
    set_session_run_state(session, RUN_STATUS_COMPLETED, "approval_approved")
    # A confirmed chat write plan becomes the request's plan (chat_write_plan).
    await activate_confirmed_plan(db, session=session, approval_id=approval.id, confirmed_by=resolved_by)
    preview_grants = await approval_grants_from_preview(db, approval_id=approval.id)
    if preview_grants:
        _append_grants(session, preview_grants)


async def _apply_session_decision(
    db: AsyncSession,
    approval: Approval,
    *,
    status: str,
    resolved_by: str | None,
    reason: str | None,
) -> None:
    session = await db.get(Session, approval.session_id)
    if session is not None:
        session.status = "active"
        if status == "approved":
            await _apply_approved(db, session, approval, resolved_by=resolved_by)
        elif status == APPROVAL_STATUS_EXPIRED:
            set_session_run_state(session, RUN_STATUS_STOPPED, "approval_timed_out")
        else:
            set_session_run_state(session, RUN_STATUS_STOPPED, "approval_rejected")
    await acknowledge_change_previews_for_approval(db, approval_id=approval.id, acknowledged_by=resolved_by)
    await create_notification(
        db,
        user_id=approval.requested_by,
        notification_type=f"approval.{status}",
        title=f"Approval {status}",
        body=reason or approval.action,
        link=f"/chat?session_id={approval.session_id}" if approval.session_id else None,
    )


async def decide_pending_approval(
    db: AsyncSession,
    *,
    approval_id: str,
    resolved_by: str | None,
    status: str,
    reason: str | None = None,
) -> Approval | None:
    """Decide ``approval_id`` only if it is still pending; ``None`` when it is unknown or already decided.

    ``resolved_by`` is ``None`` for a decision nobody made (a gate timeout).
    """
    approval = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one_or_none()
    if approval is None or approval.status != "pending":
        return None
    await _require_four_eyes(db, approval, resolved_by=resolved_by, status=status)
    claimed = await db.execute(
        update(Approval)
        .where(Approval.id == approval_id, Approval.status == "pending")
        # The request's reason is kept; the decider's note is stored next to it.
        .values(status=status, approved_by=resolved_by, decision_note=reason, resolved_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if int(claimed.rowcount or 0) != 1:
        return None
    await db.refresh(approval)
    await record_approval_decided(db, approval)
    if approval.session_id:
        await _apply_session_decision(db, approval, status=status, resolved_by=resolved_by, reason=reason)
    # A workflow run that waits for this approval moves on, after the session grants above exist.
    from ..workflow_runs.approvals import on_approval_decided

    await on_approval_decided(db, approval)
    await db.flush()
    return approval
