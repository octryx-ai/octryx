"""``budget`` problems: active budget policies that reached their warn or block threshold this period.

The budget service writes one ``budget_alerts`` row per policy, metric and threshold level per reset period when
usage crosses ``warn_at_percent`` (``warning``) or ``block_at_percent`` (``block``) (``services/budget/enforcement``).
That row is the cheap read: no usage is recomputed here. A ``block`` is a problem, a ``warning`` needs attention;
a metric that reached ``block`` is reported once, as blocked. Only alerts of the policy's current period count;
there is one per level and period, so ``since`` and ``last_seen`` are that alert. A policy without a Workspace
(person or team scope) is platform-wide.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BudgetAlert, BudgetPolicy
from ...models.runtime.budget import RESET_PERIOD_DAILY, RESET_PERIOD_MONTHLY, RESET_PERIOD_WEEKLY
from ..budget.policy_scope import _policy_window
from .links import TARGET_BUDGET, fix_link
from .model import KIND_BUDGET, SEVERITY_ATTENTION, SEVERITY_PROBLEM, CollectContext, Problem, workspace_of

LEVEL_BLOCK = "block"
LEVEL_WARNING = "warning"
_PERIODIC = (RESET_PERIOD_DAILY, RESET_PERIOD_WEEKLY, RESET_PERIOD_MONTHLY)
# The longest reset period a current alert can be from (monthly); ``never`` policies keep the 7-day window.
_LONGEST_PERIOD = timedelta(days=31)


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    alert = BudgetAlert
    workspace = func.coalesce(BudgetPolicy.project_id, "")
    rows = (await db.execute(
        select(BudgetPolicy, alert.metric_name, alert.threshold_level, func.max(alert.created_at),
               func.max(alert.percent_used))
        .join(BudgetPolicy, BudgetPolicy.id == alert.policy_id)
        .where(BudgetPolicy.is_active.is_(True), alert.threshold_level.in_((LEVEL_BLOCK, LEVEL_WARNING)),
               alert.created_at >= ctx.now - _LONGEST_PERIOD, ctx.scope(workspace))
        .group_by(BudgetPolicy.id, alert.metric_name, alert.threshold_level)
        .order_by(func.max(alert.created_at).desc()).limit(ctx.limit)
    )).all()
    current: dict[tuple[str, str], tuple] = {}
    for policy, metric, level, last, percent in rows:
        periodic = (policy.reset_period or RESET_PERIOD_DAILY).lower() in _PERIODIC
        if last < (_policy_window(policy, ctx.now)[0] if periodic else ctx.window_start):
            continue
        known = current.get((policy.id, metric))
        if known is None or (level == LEVEL_BLOCK and known[1] != LEVEL_BLOCK):
            current[(policy.id, metric)] = (policy, level, last, percent)
    problems = []
    for (_, metric), (policy, level, last, percent) in current.items():
        blocked = level == LEVEL_BLOCK
        state = "is blocked" if blocked else "passed its warning threshold"
        problems.append(Problem(
            kind=KIND_BUDGET, severity=SEVERITY_PROBLEM if blocked else SEVERITY_ATTENTION, object_type="budget",
            object_id=policy.id, object_name=policy.name, reason_code=f"{level}_{metric}",
            title=f"Budget {policy.name} {state} on {metric} ({int(percent or 0)}% used).",
            since=last, last_seen=last, workspace_id=workspace_of(policy.project_id),
            fix=fix_link(TARGET_BUDGET, workspace_id=policy.project_id, object_id=policy.id),
        ))
    return problems


__all__ = ["LEVEL_BLOCK", "LEVEL_WARNING", "collect"]
