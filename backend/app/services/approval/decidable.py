"""The pending approvals a person may decide: one circle for the phone list and the push.

``GET /api/v1/approvals/decidable`` listed them; the attention queue only knew the approvals of the
person's own sessions, so a decider of someone else's session or task run would never be pushed. Both call
:func:`decidable_approvals`: whoever sees an approval in the list gets the push, and
nobody else. Each approval passes the check its decision runs (session write access, or the sessionless rule).
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, User
from .access import approval_visibility_clause, require_sessionless_approval_access


async def may_decide(db: AsyncSession, approval: Approval, user_id: str) -> bool:
    """The decision's own access check, as a yes/no (``decide_session_approval`` / ``decide_sessionless_approval``)."""
    from ..session.turn_approval_state import require_approval_decision_access

    try:
        if approval.session_id:
            await require_approval_decision_access(db, approval=approval, user_id=user_id)
        else:
            await require_sessionless_approval_access(db, approval=approval, user_id=user_id)
    except HTTPException:
        return False
    return True


async def decidable_approvals(db: AsyncSession, user: User, *, limit: int) -> list[Approval]:
    """Up to ``limit`` pending approvals ``user`` may decide, newest first.

    ``limit`` counts decidable approvals, not visible ones: a global admin sees every pending approval, most of them
    not theirs to decide, and those must not push the decidable ones out of the list."""
    query = select(Approval).where(Approval.status == "pending")
    visible = await approval_visibility_clause(db, user.id)
    if visible is not None:
        query = query.where(visible)
    found: list[Approval] = []
    for approval in (await db.execute(query.order_by(Approval.created_at.desc()))).scalars():
        if await may_decide(db, approval, user.id):
            found.append(approval)
            if len(found) >= limit:
                break
    return found


__all__ = ["decidable_approvals", "may_decide"]
