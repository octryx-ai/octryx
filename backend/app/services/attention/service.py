"""``GET /api/v1/attention``: everything that needs the person, each entry with the requests that answer it."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from .activity_items import activity_entries
from .device_items import live_entries, turn_entries
from .dismissals import dismissed_keys
from .handover_items import handover_entries
from .run_items import finished_entries, run_entries
from .running import running_runs
from .session_items import device_approval_entries, question_entries, tool_approval_entries
from .thresholds import threshold_entries

MAX_ITEMS = 100
_ORDER = {"action": 0, "warning": 1, "info": 2}


async def attention(db: AsyncSession, user: User) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    items += await question_entries(db, user)
    items += await device_approval_entries(db, user)
    items += await tool_approval_entries(db, user)
    items += await run_entries(db, user)
    items += await handover_entries(db, user)
    dismissed = await dismissed_keys(db, user)
    items += await finished_entries(db, user, dismissed)
    items += await live_entries(db, user, dismissed)  # a session wrote back, a Mac turn ended
    items += await turn_entries(db, user, dismissed)
    items += await threshold_entries(db, user)
    items += await activity_entries(db, user)  # a run loops or stands still, a device job stalls
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    items.sort(key=lambda item: _ORDER.get(str(item.get("severity")), 3))
    items = items[:MAX_ITEMS]
    stamps = [item["created_at"] for item in items if item.get("created_at")]
    return {"items": items, "running": await running_runs(db, user), "count": len(items),
            "needs_you": sum(1 for item in items if item.get("severity") == "action"),
            "cursor": max(stamps) if stamps else None, "quiet": await _quiet(db, user)}


async def _quiet(db: AsyncSession, user: User) -> dict[str, Any]:
    from ...models import NotificationPreference
    from ...time_utils import utc_now_aware
    from .quiet_hours import quiet_state

    pref = await db.get(NotificationPreference, user.id)
    return quiet_state(pref.quiet_hours if pref is not None else None, now=utc_now_aware())


__all__ = ["attention"]
