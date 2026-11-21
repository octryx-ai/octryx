"""Takeover states, refusal codes and audit actions, plus the expiry of pending takeovers."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItemTakeover
from ...time_utils import utc_now

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_DECLINED = "declined"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
STATUSES = frozenset({STATUS_PENDING, STATUS_CONFIRMED, STATUS_DECLINED, STATUS_EXPIRED, STATUS_CANCELLED})
DEFAULT_TTL = timedelta(hours=24)
AUTHOR_SYSTEM = "system"
DECIDED_BY_HUMAN = "human"
DECIDED_BY_SYSTEM = "system"
CODE_NOT_PENDING = "takeover_not_pending"
CODE_NOT_CLAIMED = "not_claimed"
CODE_ALREADY_HOLDER = "already_holder"
CODE_REQUESTER_NOT_MEMBER = "requester_not_member"
CONFIRM_AUDIT_ACTION = "agent_board.takeover.confirmed"
TRANSFER_AUDIT_ACTION = "agent_board.takeover.claim_transferred"
DECLINE_AUDIT_ACTION = "agent_board.takeover.declined"


def effective_status(takeover: WorkItemTakeover, now=None) -> str:
    if takeover.status == STATUS_PENDING and takeover.expires_at <= (now or utc_now()):
        return STATUS_EXPIRED
    return takeover.status


async def expire_pending(db: AsyncSession, *, work_item_id: str | None = None) -> None:
    """Store ``expired`` on pending takeovers past their time (compare-and-set)."""
    statement = update(WorkItemTakeover).where(
        WorkItemTakeover.status == STATUS_PENDING, WorkItemTakeover.expires_at <= utc_now()
    )
    if work_item_id:
        statement = statement.where(WorkItemTakeover.work_item_id == work_item_id)
    await db.execute(statement.values(status=STATUS_EXPIRED).execution_options(synchronize_session="fetch"))
