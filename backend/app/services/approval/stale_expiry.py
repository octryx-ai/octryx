"""Stale pending approvals expire."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import Approval, AuditLog
from ...time_utils import utc_now
from .resolution_service import APPROVAL_STATUS_EXPIRED, decide_pending_approval

logger = logging.getLogger(__name__)

EXPIRED_AUDIT_ACTION = "approval.expired"
SWEEP_INTERVAL_SECONDS = 300
SWEEP_BATCH = 200


def pending_ttl_hours() -> int:
    return max(0, int(get_settings().approval_pending_ttl_hours or 0))


async def expire_stale_approvals(db: AsyncSession, *, ttl_hours: int | None = None) -> int:
    ttl = pending_ttl_hours() if ttl_hours is None else ttl_hours
    if ttl <= 0:
        return 0
    cutoff = utc_now() - timedelta(hours=ttl)
    rows = await db.execute(
        select(Approval.id)
        .where(
            Approval.status == "pending",
            Approval.created_at < cutoff,
        )
        .order_by(Approval.created_at)
        .limit(SWEEP_BATCH)
    )
    reason = f"No decision within {ttl} h; the approval expired."
    expired = 0
    for approval_id in rows.scalars().all():
        decided = await decide_pending_approval(
            db, approval_id=approval_id, resolved_by=None, status=APPROVAL_STATUS_EXPIRED, reason=reason
        )
        if decided is None:
            continue  # decided concurrently
        db.add(AuditLog(
            user_id=decided.requested_by,
            session_id=decided.session_id,
            action=EXPIRED_AUDIT_ACTION,
            resource_type="approval",
            resource_id=decided.id,
            project_id=decided.workspace_id,
            details={"action": decided.action, "ttl_hours": ttl,
                     "requested_at": decided.created_at.isoformat() if decided.created_at else None,
                     "expired_at": decided.resolved_at.isoformat() if decided.resolved_at else None},
        ))
        expired += 1
    await db.commit()
    if expired:
        logger.info("approval.stale_expired", extra={"expired": expired, "ttl_hours": ttl})
    return expired


class StaleApprovalExpiryWorker:
    def __init__(self, session_factory, *, interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None and pending_ttl_hours() > 0:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                async with self._session_factory() as db:
                    await expire_stale_approvals(db)
            except Exception:
                logger.exception("Stale approval expiry sweep failed")
            await asyncio.sleep(self._interval_seconds)


__all__ = ["EXPIRED_AUDIT_ACTION", "StaleApprovalExpiryWorker", "expire_stale_approvals"]
