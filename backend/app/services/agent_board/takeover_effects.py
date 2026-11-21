"""What follows a takeover decision: open notifications about it are resolved, and a confirmed
takeover turns the latest handoff's decisions, pitfalls and rules into Workspace memory (``handoff_memory``).

Kept apart from the decision itself (``takeovers.py``) so the decision stays a pure state change and the
follow-ups (notifications, knowledge memory items) can grow without touching it.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Notification, WorkItemTakeover
from ...time_utils import utc_now
from .handoff_memory import capture_latest_handoff_memory
from .takeover_status import STATUS_CONFIRMED

NOTIFICATION_PREFIX = "agent_board."


async def resolve_takeover_notifications(db: AsyncSession, takeover_id: str) -> None:
    await db.execute(
        update(Notification)
        .where(
            Notification.type.like(f"{NOTIFICATION_PREFIX}%"),
            Notification.link.like(f"%&takeover_id={takeover_id}"),
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=utc_now())
        .execution_options(synchronize_session=False)
    )


async def after_takeover_decision(db: AsyncSession, takeover: WorkItemTakeover, *, actor_user_id: str) -> None:
    """Resolve the decided takeover's notifications; a confirmed one keeps the handoff's lessons as memory."""
    await resolve_takeover_notifications(db, takeover.id)
    if takeover.status == STATUS_CONFIRMED:
        await capture_latest_handoff_memory(db, takeover.work_item_id)


__all__ = ["after_takeover_decision", "resolve_takeover_notifications"]
