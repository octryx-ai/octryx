"""Stale pending approvals expire after the TTL with an audit row; fresh approvals stay."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import Approval, AuditLog, User
from app.services.approval.stale_expiry import EXPIRED_AUDIT_ACTION, expire_stale_approvals
from app.time_utils import utc_now


async def test_a_pending_approval_older_than_the_ttl_expires_with_an_audit_row(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    old = utc_now() - timedelta(hours=80)
    stale = Approval(requested_by=admin.id, action="tool:shell", created_at=old)
    fresh = Approval(requested_by=admin.id, action="tool:shell", created_at=utc_now() - timedelta(hours=1))
    db.add_all([stale, fresh])
    await db.commit()

    assert await expire_stale_approvals(db, ttl_hours=0) == 0, "0 never expires"
    assert await expire_stale_approvals(db, ttl_hours=72) == 1
    for row in (stale, fresh):
        await db.refresh(row)
    assert (stale.status, fresh.status) == ("expired", "pending")
    # The expiry note is the decision's (observability O2: ``decision_note``); the request's reason is kept.
    assert stale.approved_by is None and "72 h" in stale.decision_note
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == EXPIRED_AUDIT_ACTION))).scalars().all()
    assert [(row.resource_id, row.user_id, row.details["ttl_hours"]) for row in audit] == [(stale.id, admin.id, 72)]
    assert await expire_stale_approvals(db, ttl_hours=72) == 0, "an expired approval is not expired twice"
