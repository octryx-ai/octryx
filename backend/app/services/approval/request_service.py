"""Approval request orchestration."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, Session
from ..outbound_webhook import emit_outbound_webhook_event
from ..session.run_state import RUN_STATUS_AWAITING_APPROVAL, set_session_run_state
from ..session.turn_approval_state import hold_turn_for_approval
from ..team_notification import notify_admins

logger = logging.getLogger(__name__)


async def _workspace_of(db: AsyncSession, *, session_id: str | None, task_run_id: str | None) -> str | None:
    """The Workspace an approval belongs to: its session's project, else its task run's task's project.

    If neither lookup resolves, ``workspace_id`` stays null and the page cannot say which Workspace asked."""
    from ...models import Task, TaskRun

    if session_id:
        session = await db.get(Session, session_id)
        if session is not None and session.project_id:
            return session.project_id
    if task_run_id:
        return (await db.execute(select(Task.project_id).join(TaskRun, TaskRun.task_id == Task.id)
                                 .where(TaskRun.id == task_run_id))).scalar_one_or_none()
    return None


def _requested_payload(approval: Approval) -> dict[str, Any]:
    """The ``approval.requested`` event payload, read from the row at the moment it is sent."""
    return {
        "approval_id": approval.id,
        "action": approval.action,
        "reason": approval.reason,
        "session_id": approval.session_id,
        "task_run_id": approval.task_run_id,
        "requested_by": approval.requested_by,
    }


async def _pending_duplicate(
    db: AsyncSession, *, requested_by: str, action: str, task_run_id: str | None, session_id: str | None
) -> Approval | None:
    """The newest pending approval for the same requester, action, task run and session."""
    query = select(Approval).where(
        Approval.requested_by == requested_by,
        Approval.action == action,
        Approval.status == "pending",
    )
    if task_run_id:
        query = query.where(Approval.task_run_id == task_run_id)
    else:
        query = query.where(Approval.task_run_id.is_(None))
    if session_id:
        query = query.where(Approval.session_id == session_id)
    else:
        query = query.where(Approval.session_id.is_(None))

    return (await db.execute(query.order_by(Approval.created_at.desc()))).scalars().first()


async def _hold_session(
    db: AsyncSession, approval: Approval, *, session_id: str, requested_by: str, action: str, reason: str | None
) -> Session | None:
    """Put the session on hold for the approval and tell the admins; returns the session row if it exists."""
    session = await db.get(Session, session_id)
    if session is not None:
        session.status = "pending_approval"
        set_session_run_state(session, RUN_STATUS_AWAITING_APPROVAL, "approval_required")
    await notify_admins(
        db,
        notification_type="approval.requested",
        title=action,
        body=reason or "Approval requested.",
        link=f"/chat?session_id={session_id}",
        payload=_requested_payload(approval),
        project_id=session.project_id if session is not None else None,
        exclude_user_id=requested_by,
    )
    return session


async def ensure_approval_request(
    db: AsyncSession,
    *,
    requested_by: str,
    action: str,
    reason: str | None = None,
    task_run_id: str | None = None,
    session_id: str | None = None,
) -> Approval:
    if not task_run_id and not session_id:
        raise ValueError("task_run_id or session_id is required")
    from ..secret_masking import masked_text

    # A summary can quote a model-written value (a request body, a comment): stored masked.
    action, reason = masked_text(action) or action, masked_text(reason)

    existing = await _pending_duplicate(
        db, requested_by=requested_by, action=action, task_run_id=task_run_id, session_id=session_id
    )
    if existing:
        if reason and not existing.reason:
            existing.reason = reason
            await db.flush()
        return existing

    approval = Approval(
        requested_by=requested_by,
        action=action,
        reason=reason,
        task_run_id=task_run_id,
        session_id=session_id,
        workspace_id=await _workspace_of(db, session_id=session_id, task_run_id=task_run_id),
    )
    db.add(approval)
    session: Session | None = None
    if session_id:
        session = await _hold_session(
            db, approval, session_id=session_id, requested_by=requested_by, action=action, reason=reason
        )
    await db.flush()
    if session is not None:
        # Bind the approval to the chat turn in flight so its decision can resume it.
        hold_turn_for_approval(session, approval_id=approval.id, requested_by=requested_by)
    try:
        await emit_outbound_webhook_event(
            db,
            event_type="approval.requested",
            project_id=session.project_id if session_id and session is not None else None,
            payload=_requested_payload(approval),
        )
    except Exception:
        logger.exception("Failed to enqueue outbound approval.requested webhook", extra={"approval_id": approval.id})
    return approval
