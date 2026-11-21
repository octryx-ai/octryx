"""The per-user daily budget for octryx-claude sessions, checked before every model dispatch.

An octryx-claude user spends at most ``session_budget.per_user_daily_usd``
of the Workspace's ``agent_gateway_policy`` (baseline: 50 USD) per UTC day. What counts is
the user's recorded gateway spend of the day — every ``UsageEvent`` on an ``octryx_claude``
shadow session, across Workspaces — against the limit of the Workspace the call is for.

The check runs before dispatch and refuses once the spend has reached the limit; the call
that crosses it is the last one served (the gateway cannot know a call's cost before the
model answers). Every outcome is explicit: no policy or no budget is
``needs_configuration``, an exhausted budget is ``denied`` with the limit and the reset time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, UsageEvent
from ...time_utils import utc_now
from .contract import (
    EXTERNAL_AGENT_TYPE,
    GATEWAY_EXTERNAL_SOURCE,
    STATE_ALLOWED,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
)
from .policy import load_workspace_policy

REASON_POLICY_INVALID = "gateway_policy_invalid"
REASON_BUDGET_NOT_CONFIGURED = "gateway_budget_not_configured"
REASON_DAILY_BUDGET_EXHAUSTED = "gateway_daily_budget_exhausted"


@dataclass(frozen=True, slots=True)
class DailyBudgetDecision:
    state: str
    reason: str = ""
    limit_usd: Decimal | None = None
    spent_usd: Decimal = Decimal("0")
    resets_at: datetime | None = None

    @property
    def allowed(self) -> bool:
        return self.state == STATE_ALLOWED

    def hint(self) -> str:
        if self.reason == REASON_DAILY_BUDGET_EXHAUSTED and self.limit_usd is not None and self.resets_at:
            return (
                f"Your octryx-claude budget of {self.limit_usd:.2f} USD for today is used up "
                f"({self.spent_usd:.2f} USD spent). It resets at {self.resets_at:%Y-%m-%d %H:%M} UTC."
            )
        if self.reason == REASON_BUDGET_NOT_CONFIGURED:
            return "The Workspace's agent_gateway_policy sets no session_budget. Ask your Octryx administrator."
        return "The Workspace's agent_gateway_policy is invalid. Ask your Octryx administrator."


def utc_day_window(now: datetime) -> tuple[datetime, datetime]:
    """Start and end of the UTC day ``now`` falls in, naive like the stored timestamps."""

    start = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    return start, start + timedelta(days=1)


async def gateway_spend_today(db: AsyncSession, *, user_id: str, day_start: datetime) -> Decimal:
    total = (
        await db.execute(
            select(func.coalesce(func.sum(UsageEvent.cost), 0))
            .join(Session, Session.id == UsageEvent.session_id)
            .where(
                UsageEvent.user_id == user_id,
                UsageEvent.created_at >= day_start,
                Session.agent_type == EXTERNAL_AGENT_TYPE,
                Session.metadata_["external_source"].as_string() == GATEWAY_EXTERNAL_SOURCE,
            )
        )
    ).scalar_one()
    return Decimal(str(total or 0))


async def check_daily_budget(
    db: AsyncSession,
    *,
    user_id: str,
    workspace_id: str,
    now: datetime | None = None,
) -> DailyBudgetDecision:
    load = await load_workspace_policy(db, workspace_id)
    if load.policy is None:
        return DailyBudgetDecision(STATE_NEEDS_CONFIGURATION, REASON_POLICY_INVALID)
    limit = load.policy.daily_budget_usd
    if limit is None:
        return DailyBudgetDecision(STATE_NEEDS_CONFIGURATION, REASON_BUDGET_NOT_CONFIGURED)
    day_start, day_end = utc_day_window(now or utc_now())
    spent = await gateway_spend_today(db, user_id=user_id, day_start=day_start)
    if spent >= limit:
        return DailyBudgetDecision(STATE_DENIED, REASON_DAILY_BUDGET_EXHAUSTED, limit, spent, day_end)
    return DailyBudgetDecision(STATE_ALLOWED, "", limit, spent, day_end)


__all__ = [
    "REASON_BUDGET_NOT_CONFIGURED",
    "REASON_DAILY_BUDGET_EXHAUSTED",
    "REASON_POLICY_INVALID",
    "DailyBudgetDecision",
    "check_daily_budget",
    "gateway_spend_today",
    "utc_day_window",
]
