"""Decide a session approval on any route, then resume what it paused (one owner).

``/chat/api/approvals/{id}/approve|reject``, the admin panel approvals,
``/api/v1/approvals/{id}/approve|reject`` and channel approval commands all call
:func:`decide_session_approval`. It enforces, in this order:

1. **who may decide**: the decider needs write access to the approval's session
   (``require_approval_decision_access``: owner, contributor, team member,
   read-write grant; else 404/403). The admin panel decides with
   :data:`AUTHORITY_PLATFORM_ADMIN`, because its route already requires a platform
   admin; that is the only other authority;
2. **still pending** (409 ``approval_already_resolved`` otherwise, ``approval/errors``);
3. **one decision**: the decision is a compare-and-set on the approval row, so a
   concurrent decider (another route, the expiry sweep) makes this one the same 409 and
   nothing is resumed twice.

The winner hands the approval to ``approval_resume.resume_decided_approval``, which
resumes the paused turn as its owner, never as the decider.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval
from ...models import Session as AgentSession
from ..approval import decide_pending_approval
from ..approval.errors import approval_already_resolved
from .approval_resume import DECISION_APPROVED, DECISION_REJECTED, resume_decided_approval
from .turn_approval_state import require_approval_decision_access

logger = logging.getLogger(__name__)

AUTHORITY_SESSION_WRITE = "session_write"
AUTHORITY_PLATFORM_ADMIN = "platform_admin"
_AUTHORITIES = frozenset({AUTHORITY_SESSION_WRITE, AUTHORITY_PLATFORM_ADMIN})
_DECISIONS = frozenset({DECISION_APPROVED, DECISION_REJECTED})


async def decide_session_approval(
    db: AsyncSession,
    *,
    approval_id: str,
    decider_id: str,
    decision: str,
    reason: str | None,
    authority: str = AUTHORITY_SESSION_WRITE,
    session_factory=None,
) -> Approval:
    """Decide a pending session approval as ``decider_id`` and resume its turn; commits."""
    if decision not in _DECISIONS or authority not in _AUTHORITIES:
        raise ValueError("unknown approval decision or authority")
    approval = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one_or_none()
    if approval is None or not approval.session_id:
        raise HTTPException(status_code=404, detail="Approval not found")
    if authority == AUTHORITY_SESSION_WRITE:
        await require_approval_decision_access(db, approval=approval, user_id=decider_id)
    if approval.status != "pending":
        raise approval_already_resolved()

    decided = await decide_pending_approval(
        db, approval_id=approval.id, resolved_by=decider_id, status=decision, reason=reason
    )
    if decided is None:
        raise approval_already_resolved()
    session = await db.get(AgentSession, decided.session_id)
    if session is None:
        await db.commit()
        return decided
    await resume_decided_approval(
        db, session=session, approval=decided, decision=decision, session_factory=session_factory
    )
    logger.info(
        "approval.decided",
        extra={"approval_id": decided.id, "decision": decision, "authority": authority},
    )
    return (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()


__all__ = [
    "AUTHORITY_PLATFORM_ADMIN",
    "AUTHORITY_SESSION_WRITE",
    "decide_session_approval",
]
