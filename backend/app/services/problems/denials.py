"""``rule_denial`` problems: rules that denied requests in the last 7 days, per Workspace and rule.

Source is ``policy_decision_log`` rows with ``outcome = denied`` (the gates' explicit refusals,
``services/decisions/recorder``), grouped in SQL by Workspace, gate and rule: first and last denial and their
number. ``policy_decision_counters`` only counts allows, so it cannot carry denials. A denial is the governance
working as configured, so it needs attention, not repair; the link opens the decisions of that rule.
A row without a rule is grouped under its gate.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PolicyDecisionLog
from ..decisions.recorder import OUTCOME_DENIED
from .links import TARGET_RULE, fix_link
from .model import KIND_RULE_DENIAL, SEVERITY_ATTENTION, CollectContext, Problem, scoped_object_id, workspace_of


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    log = PolicyDecisionLog
    workspace = func.coalesce(log.workspace_id, "")
    rows = (await db.execute(
        select(workspace, log.gate, log.rule, func.min(log.created_at), func.max(log.created_at), func.count())
        .where(log.outcome == OUTCOME_DENIED, log.created_at >= ctx.window_start, ctx.scope(workspace))
        .group_by(workspace, log.gate, log.rule)
        .order_by(func.count().desc()).limit(ctx.limit)
    )).all()
    problems = []
    for workspace_id, gate, rule, first, last, count in rows:
        workspace_id = workspace_of(workspace_id)
        rule_id = str(rule or gate or "unknown")
        times = "once" if count == 1 else f"{count} times"
        problems.append(Problem(
            kind=KIND_RULE_DENIAL, severity=SEVERITY_ATTENTION, object_type="rule", object_id=rule_id,
            object_name=rule_id, key_object_id=scoped_object_id(rule_id, workspace_id), reason_code="denied",
            title=f"Rule {rule_id} denied requests {times} in the last 7 days.",
            since=first, last_seen=last, count=int(count), workspace_id=workspace_id,
            fix=fix_link(TARGET_RULE, workspace_id=workspace_id, object_id=rule_id if rule else None),
        ))
    return problems


__all__ = ["collect"]
