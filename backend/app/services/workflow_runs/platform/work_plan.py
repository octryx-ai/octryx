"""``work.draft_change_plan``: the run's Work item gets its change plan from the submitted test contract."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun
from ....models.runtime.secure_work import WorkItem
from .dispatch import FAILED, SUCCEEDED, ToolOutcome

DRAFTED_PLAN_KEY = "change_plan"


async def draft_change_plan(db: AsyncSession, run: WorkflowRun) -> ToolOutcome:
    from ...secure_work.plans.run_plan import draft_run_plan
    from ..confirmation_payloads import plan_hash
    from ..phase_outputs import recorded_output

    envelope = recorded_output(run, "test_contract")
    if envelope is None:
        return ToolOutcome(FAILED, reason="no test contract was submitted in this run")
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None:
        return ToolOutcome(FAILED, reason="the run has no Work item to hold the change plan")
    if item.project_id != run.project_id:
        return ToolOutcome(FAILED, reason="the Work item belongs to another Workspace than the run")
    requester = await db.get(User, run.requested_by)
    if requester is None:
        return ToolOutcome(FAILED, reason="the run's requester no longer exists")
    from ..succession import earlier_runs

    earlier = [row.id for row in await earlier_runs(db, run, same_repository=False)]
    plan = await draft_run_plan(db, item=item, requester=requester, run_id=run.id, node_id=run.current_node_id or "",
                                envelope=envelope, earlier_run_ids=earlier)
    drafted = {"id": plan.id, "version": plan.version, "hash": plan_hash(plan),
               "test_contract_version": envelope.get("version")}
    drafted_by = str(dict(plan.evidence_json or {}).get("workflow_run_id") or "")
    if drafted_by and drafted_by != run.id:
        drafted["adopted_from_run"] = drafted_by
    run.context = {**dict(run.context or {}), DRAFTED_PLAN_KEY: drafted}
    return ToolOutcome(SUCCEEDED, {"change_plan_id": plan.id, "version": plan.version, "status": plan.status})


__all__ = ["DRAFTED_PLAN_KEY", "draft_change_plan"]
