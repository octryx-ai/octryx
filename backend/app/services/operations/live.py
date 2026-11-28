"""The whole live view: runs, devices, seats and counts, in the Problems scope (``services/problems/scope``)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...time_utils import utc_now
from ..problems import activity
from ..problems.model import iso
from ..problems.scope import ProblemScope
from . import fleet
from .runs import STATES, live_runs


async def live_view(db: AsyncSession, user: User, scope: ProblemScope, *, now: datetime | None = None
                    ) -> dict[str, Any]:
    now = now or utc_now()
    ctx = scope.context(now)
    problems = await activity.collect(db, ctx)
    runs = await live_runs(db, viewer_id=user.id, scope=ctx.scope, now=now, problems=problems)
    states = Counter(row["state"] for row in runs)
    return {
        "generated_at": iso(now),
        "viewer": {"id": user.id},
        "counts": {**{state: states[state] for state in STATES},
                   **await fleet.cost_24h(db, scope=ctx.scope, now=now)},
        "runs": runs,
        "devices": await fleet.devices(db, viewer_id=user.id, scope=ctx.scope,
                                       platform_wide=scope.workspace_ids is None, now=now),
        "seats": await fleet.seats(db, viewer_id=user.id, scope=ctx.scope, now=now),
    }


__all__ = ["live_view"]
