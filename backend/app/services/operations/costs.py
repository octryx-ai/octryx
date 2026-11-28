"""What the agent work cost and what it delivered: per workflow, work item, run, person or Workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, UsageEvent, User, WorkflowRun, WorkflowRunSession
from ...models.runtime.secure_work import WorkItem
from ..problems.model import iso

GROUPS = ("workflow", "work_item", "run", "person", "workspace")
MAX_DAYS = 366


class CostQueryError(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field, self.message = field, message


SEAT_COST_SOURCE = "seat_subscription"


@dataclass
class RunCost:
    api_usd: float = 0.0
    seat_api_equivalent_usd: float = 0.0
    seat_unpriced_calls: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"cost_usd": round(self.api_usd, 6), "seat_api_equivalent_usd": round(self.seat_api_equivalent_usd, 6),
                "seat_unpriced_calls": self.seat_unpriced_calls}


async def run_cost_split(db: AsyncSession, run_ids: list[str]) -> dict[str, RunCost]:
    if not run_ids:
        return {}
    pairs = set((await db.execute(select(WorkflowRunSession.run_id, WorkflowRunSession.session_id)
                                  .where(WorkflowRunSession.run_id.in_(run_ids)))).all())
    sessions = sorted({sid for _, sid in pairs})
    per_session: dict[str, tuple[float, float, int]] = {}
    if sessions:
        seat = UsageEvent.cost_source == SEAT_COST_SOURCE
        rows = (await db.execute(
            select(UsageEvent.session_id, func.sum(UsageEvent.cost),
                   func.sum(case((seat, UsageEvent.list_cost), else_=None)),
                   func.sum(case((seat & UsageEvent.list_cost.is_(None), 1), else_=0)))
            .where(UsageEvent.session_id.in_(sessions)).group_by(UsageEvent.session_id))).all()
        per_session = {sid: (float(cost or 0), float(listed or 0), int(unpriced or 0))
                       for sid, cost, listed, unpriced in rows}
    totals = {run_id: RunCost() for run_id in run_ids}
    for run_id, sid in pairs:
        cost, listed, unpriced = per_session.get(sid, (0.0, 0.0, 0))
        total = totals[run_id]
        total.api_usd += cost
        total.seat_api_equivalent_usd += listed
        total.seat_unpriced_calls += unpriced
    return totals


async def run_costs(db: AsyncSession, run_ids: list[str]) -> dict[str, float]:
    return {run_id: round(cost.api_usd, 6) for run_id, cost in (await run_cost_split(db, run_ids)).items()}


def _has_pr(run: WorkflowRun) -> bool:
    url = str(dict(run.pull_request or {}).get("url") or "")
    return url.startswith(("https://", "http://"))


async def _labels(db: AsyncSession, group: str, keys: set[str], runs: list[WorkflowRun]) -> dict[str, str]:
    keys = {key for key in keys if key}
    if not keys:
        return {}
    if group == "workspace":
        return dict((await db.execute(select(Project.id, Project.name).where(Project.id.in_(keys)))).all())
    if group == "person":
        return {user.id: user.display_name or user.username
                for user in (await db.execute(select(User).where(User.id.in_(keys)))).scalars()}
    if group == "work_item":
        return {item.id: f"{item.source_key} {item.title}".strip() if item.source_key else item.title
                for item in (await db.execute(select(WorkItem).where(WorkItem.id.in_(keys)))).scalars()}
    if group == "run":
        return {run.id: run.title or run.workflow_key for run in runs}
    # Workflows by their published name ("Feature delivery (TDD)"), the key when unnamed.
    from ...models import FlowDefinition

    names = {key: name for key, name in (await db.execute(
        select(FlowDefinition.key, FlowDefinition.name).where(FlowDefinition.key.in_(keys)))).all() if name}
    return {key: names.get(key) or key for key in keys}


def _key(run: WorkflowRun, group: str) -> str | None:
    return {"workflow": run.workflow_key, "work_item": run.work_item_id, "run": run.id,
            "person": run.requested_by, "workspace": run.project_id}[group]


async def cost_report(db: AsyncSession, *, scope: Any, now: datetime, days: int, group: str) -> dict[str, Any]:
    if group not in GROUPS:
        raise CostQueryError("group", f"Unknown group '{group}'; use one of: {', '.join(GROUPS)}.")
    if not 1 <= days <= MAX_DAYS:
        raise CostQueryError("days", f"days must be between 1 and {MAX_DAYS}.")
    since = now - timedelta(days=days)
    runs = list((await db.execute(select(WorkflowRun).where(
        WorkflowRun.created_at >= since, scope(WorkflowRun.project_id)))).scalars())
    costs = await run_cost_split(db, [run.id for run in runs])
    rows: dict[str, dict[str, Any]] = {}
    for run in runs:
        key = _key(run, group) or "-"
        row = rows.setdefault(key, {"key": key, "runs": 0, "delivered": 0, "pull_requests": 0, "cost_usd": 0.0,
                                    "seat_api_equivalent_usd": 0.0, "seat_unpriced_calls": 0})
        row["runs"] += 1
        row["delivered"] += int(run.status == "completed")
        row["pull_requests"] += int(_has_pr(run))
        cost = costs.get(run.id) or RunCost()
        row["cost_usd"] += cost.api_usd
        row["seat_api_equivalent_usd"] += cost.seat_api_equivalent_usd
        row["seat_unpriced_calls"] += cost.seat_unpriced_calls
    labels = await _labels(db, group, set(rows), runs)
    groups = []
    for key, row in rows.items():
        cost = round(row["cost_usd"], 6)
        groups.append({**row, "cost_usd": cost, "seat_api_equivalent_usd": round(row["seat_api_equivalent_usd"], 6),
                       "label": labels.get(key) or ("(none)" if key == "-" else key),
                       "cost_per_delivered_usd": round(cost / row["delivered"], 6) if row["delivered"] else None})
    groups.sort(key=lambda row: -row["cost_usd"])
    total = round(sum(row["cost_usd"] for row in groups), 6)
    delivered = sum(row["delivered"] for row in groups)
    return {
        "window": {"from": iso(since), "to": iso(now), "days": days}, "group": group,
        "totals": {"runs": len(runs), "delivered": delivered,
                   "pull_requests": sum(row["pull_requests"] for row in groups), "cost_usd": total,
                   "seat_api_equivalent_usd": round(sum(row["seat_api_equivalent_usd"] for row in groups), 6),
                   "seat_unpriced_calls": sum(row["seat_unpriced_calls"] for row in groups),
                   "cost_per_delivered_usd": round(total / delivered, 6) if delivered else None},
        "groups": groups,
    }


__all__ = ["GROUPS", "CostQueryError", "RunCost", "cost_report", "run_cost_split", "run_costs"]
