"""A workflow run's change plan, drafted on the server from the test contract its phase submitted.

The clarify phase of a run is read-only and its agent holds no ``work:manage``: it submits the test contract as
data (``workflow_runs/phase_outputs``) and the run's ``work.draft_change_plan`` step calls :func:`draft_run_plan`.
The plan is a normal versioned change plan of the Work item (the same table, lock, supersede rule and audit as
``change_plans.generate_change_plan``), created for the run's requester, with the run's identity in its evidence:

- each criterion keeps its tests (``tests``, each with its role in ``test_roles``: new / regression) and its command
  (``validation_commands``); the command is an enforceable entry of the validation plan, so the acceptance-coverage
  gate sees it;
- a manual-only criterion has no command (``manual_only`` with its reason): the person who confirms the plan takes
  it over explicitly (``human_verified_criteria``, recorded in the decision);
- idempotent per contract: an open plan already drafted from the same contract hash for the same run — or for an
  earlier, ended run of the same Work item (succession) — is returned as it is; another contract supersedes the open
  plans and becomes the next version.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, User, WorkChangePlan, WorkItem
from .plan_records import OPEN_PLAN_STATUSES, _next_version, _supersede_open_plans
from .plan_write_lock import lock_work_item_for_plan_write

PLAN_SOURCE = "workflow_run_test_contract"


def plan_rows(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(acceptance_criteria, validation_plan)`` of a recorded test contract."""
    criteria: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    for criterion in contract.get("criteria") or []:
        row = {"id": criterion["id"], "text": criterion["text"], "source": PLAN_SOURCE}
        if criterion.get("manual_only"):
            row.update(validation_commands=[], tests=[], manual_only=True,
                       manual_reason=criterion.get("manual_reason") or "")
        else:
            row.update(validation_commands=[criterion["command"]], tests=list(criterion.get("tests") or []),
                       test_roles=dict(criterion.get("test_roles") or {}))
            if all(entry["command"] != criterion["command"] for entry in validation):
                validation.append({"command": criterion["command"], "source": PLAN_SOURCE,
                                   "criteria": [criterion["id"]]})
            else:
                next(entry for entry in validation if entry["command"] == criterion["command"])["criteria"].append(
                    criterion["id"])
        criteria.append(row)
    return criteria, validation


async def _drafted_open_plan(db: AsyncSession, item_id: str, run_ids: list[str],
                             contract_hash: str) -> WorkChangePlan | None:
    """The newest open plan drafted from ``contract_hash`` by one of ``run_ids`` (this run first, then earlier ones)."""
    rows = (await db.execute(select(WorkChangePlan).where(
        WorkChangePlan.work_item_id == item_id, WorkChangePlan.status.in_(OPEN_PLAN_STATUSES),
    ).order_by(WorkChangePlan.version.desc()))).scalars().all()
    for run_id in run_ids:
        found = next((row for row in rows if dict(row.evidence_json or {}).get("workflow_run_id") == run_id
                      and dict(row.evidence_json or {}).get("test_contract_hash") == contract_hash), None)
        if found is not None:
            return found
    return None


async def draft_run_plan(
    db: AsyncSession, *, item: WorkItem, requester: User, run_id: str, node_id: str, envelope: dict[str, Any],
    earlier_run_ids: list[str] | None = None,
) -> WorkChangePlan:
    """The Work item's open change plan for the run's recorded test contract ``envelope`` (created or reused).

    ``earlier_run_ids``: the ended runs of the same item (newest first) whose still-open plan of the *same* contract
    is adopted instead of a new version; a decided plan is never adopted (its confirmation was the earlier run's)."""
    contract = dict(envelope.get("record") or {})
    contract_hash = str(envelope.get("hash") or "")
    await lock_work_item_for_plan_write(db, item.id)
    existing = await _drafted_open_plan(db, item.id, [run_id, *(earlier_run_ids or [])], contract_hash)
    if existing is not None:
        return existing
    criteria, validation = plan_rows(contract)
    version = await _next_version(db, item.id)
    superseded = await _supersede_open_plans(db, item.id, requester.id, True)
    questions = list(contract.get("open_questions") or [])
    status = "needs_clarification" if questions else "ready_for_review"
    row = WorkChangePlan(
        work_item_id=item.id, supersedes_plan_id=superseded, version=version, status=status,
        title=f"{item.source_key} test contract"[:500], understood_request=str(contract.get("summary") or "") or None,
        assumptions_json=[], open_questions_json=questions, affected_repositories_json=[], change_units_json=[],
        proposed_branches_json=[], planned_files_json=[], validation_plan_json=validation,
        acceptance_criteria_json=criteria, security_risks_json=[], reviewer_recommendations_json=[],
        required_approvals_json=[], expected_prs_json=[], trace_refs_json=[],
        evidence_json={"plan_type": "coding_change", "source": PLAN_SOURCE, "workflow_run_id": run_id,
                       "node_id": node_id, "test_contract_version": envelope.get("version"),
                       "test_contract_hash": contract_hash},
        jira_sync_preview_json={}, created_by=requester.id, updated_by=requester.id,
    )
    db.add(row)
    await db.flush()
    db.add(AuditLog(user_id=requester.id, action="secure_work.change_plan_drafted_by_run", resource_type="work_item",
                    resource_id=item.id, details={"source_key": item.source_key, "change_plan_id": row.id,
                                                  "version": version, "status": status, "workflow_run_id": run_id,
                                                  "test_contract_hash": contract_hash}))
    await db.flush()
    return row


__all__ = ["PLAN_SOURCE", "draft_run_plan", "plan_rows"]
