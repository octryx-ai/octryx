from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    User,
    WorkChangePlan,
    WorkChangePlanDecision,
    WorkItem,
    WorkItemChangeUnit,
    WorkItemWorkflowDefinition,
)
from ....time_utils import utc_now
from ..jira_values import blank_to_none, object_value, string_list
from ..plan_serializers import serialize_change_plan, serialize_change_plan_decision
from ..related_rows import WORKFLOW, load_optional_related
from ..reviewers import recommend_reviewers_for_work_item
from .acceptance_coverage import acceptance_coverage_blockers
from .deterministic_plan_data import _plan_data_from_inputs
from .plan_records import (
    _audit_log,
    _jira_sync_preview,
    _next_version,
    _supersede_open_plans,
)
from .plan_write_lock import lock_work_item_for_plan_write, reread_plan
from .redeclare import SUPERSEDED_UNIT_STATUS

PLAN_DECISIONS = {
    "approve": "approved",
    "reject": "rejected",
    "request_clarification": "needs_clarification",
}


async def list_change_plans(db: AsyncSession, work_item_id: str) -> list[dict[str, Any]]:
    stmt = (
        select(WorkChangePlan)
        .where(WorkChangePlan.work_item_id == work_item_id)
        .order_by(WorkChangePlan.version.desc(), WorkChangePlan.created_at.desc())
    )
    return [serialize_change_plan(row) for row in (await db.execute(stmt)).scalars().all()]


async def get_change_plan(db: AsyncSession, change_plan_id: str) -> WorkChangePlan:
    row = await db.get(WorkChangePlan, change_plan_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Change Plan not found")
    return row


async def generate_change_plan(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    workflow = await load_optional_related(
        db, current_user, WORKFLOW, blank_to_none(payload.get("workflow_id")), for_workspace=item.project_id
    )
    units = await _active_change_units(db, item.id)
    recommendation_payload = await recommend_reviewers_for_work_item(db, item.id, viewer=current_user,
                                                                     workspace_id=item.project_id)
    await lock_work_item_for_plan_write(db, item.id)
    version = await _next_version(db, item.id)
    superseded_plan_id = await _supersede_open_plans(
        db,
        item.id,
        current_user.id,
        bool(payload.get("supersede_existing", True)),
    )
    plan_data = _plan_data_from_inputs(
        item=item,
        units=units,
        reviewer_payload=recommendation_payload,
        workflow=workflow,
        payload=payload,
    )
    status = "needs_clarification" if plan_data["open_questions"] else "ready_for_review"
    row = _deterministic_plan_row(
        item=item,
        workflow=workflow,
        plan_data=plan_data,
        payload=payload,
        version=version,
        superseded_plan_id=superseded_plan_id,
        status=status,
        current_user=current_user,
    )
    db.add(row)
    await db.flush()
    db.add(
        _audit_log(
            current_user,
            item,
            "secure_work.change_plan_generated",
            {"change_plan_id": row.id, "version": version, "status": status},
        )
    )
    await db.flush()
    return serialize_change_plan(row)


async def _active_change_units(db: AsyncSession, work_item_id: str) -> list[WorkItemChangeUnit]:
    return (
        await db.execute(
            select(WorkItemChangeUnit)
            .where(
                WorkItemChangeUnit.work_item_id == work_item_id,
                WorkItemChangeUnit.status != SUPERSEDED_UNIT_STATUS,
            )
            .order_by(WorkItemChangeUnit.dependency_order.asc(), WorkItemChangeUnit.created_at.asc())
        )
    ).scalars().all()


def _deterministic_plan_row(
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition | None,
    plan_data: dict[str, Any],
    payload: dict[str, Any],
    version: int,
    superseded_plan_id: str | None,
    status: str,
    current_user: User,
) -> WorkChangePlan:
    return WorkChangePlan(
        work_item_id=item.id,
        workflow_id=workflow.id if workflow else None,
        supersedes_plan_id=superseded_plan_id,
        version=version,
        status=status,
        title=str(payload.get("title") or f"{item.source_key} Change Plan")[:500],
        understood_request=plan_data["understood_request"],
        assumptions_json=plan_data["assumptions"],
        open_questions_json=plan_data["open_questions"],
        affected_repositories_json=plan_data["affected_repositories"],
        change_units_json=plan_data["change_units"],
        proposed_branches_json=plan_data["proposed_branches"],
        planned_files_json=plan_data["planned_files"],
        validation_plan_json=plan_data["validation_plan"],
        acceptance_criteria_json=plan_data["acceptance_criteria"],
        security_risks_json=plan_data["security_risks"],
        reviewer_recommendations_json=plan_data["reviewer_recommendations"],
        required_approvals_json=plan_data["required_approvals"],
        expected_prs_json=plan_data["expected_prs"],
        rollback_plan=plan_data["rollback_plan"],
        trace_refs_json=plan_data["trace_refs"],
        evidence_json=plan_data["evidence"],
        jira_sync_preview_json=_jira_sync_preview(
            workflow=workflow,
            target_state=str(payload.get("target_state") or status),
            source="change_plan_generation",
        ),
        created_by=current_user.id,
        updated_by=current_user.id,
    )


async def decide_change_plan(
    db: AsyncSession,
    *,
    change_plan_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    plan = await get_change_plan(db, change_plan_id)
    # Serialize with every other plan writer of this Work Item, then validate the stored status,
    # not a copy loaded before the lock.
    item = await lock_work_item_for_plan_write(db, plan.work_item_id)
    plan = await reread_plan(db, change_plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Change Plan not found")
    action, reason, required_changes, human_verified_criteria = _validated_decision(plan, payload)
    to_status = PLAN_DECISIONS[action]
    workflow = await load_optional_related(
        db, current_user, WORKFLOW, blank_to_none(payload.get("workflow_id")) or plan.workflow_id,
        for_workspace=item.project_id,
    )
    jira_sync_preview = _jira_sync_preview(
        workflow=workflow,
        target_state=str(payload.get("target_state") or to_status),
        source=f"change_plan_{action}",
    )
    decision = WorkChangePlanDecision(
        change_plan_id=plan.id,
        work_item_id=plan.work_item_id,
        actor_id=current_user.id,
        action=action,
        from_status=plan.status,
        to_status=to_status,
        reason=reason,
        required_changes_json=required_changes,
        jira_sync_preview_json=jira_sync_preview,
        evidence_json=_decision_evidence(payload, action=action, human_verified_criteria=human_verified_criteria),
    )
    _apply_decision(plan, action=action, to_status=to_status, actor_id=current_user.id, preview=jira_sync_preview)
    db.add(decision)
    db.add(
        _audit_log(
            current_user,
            item,
            f"secure_work.change_plan_{action}",
            {
                "change_plan_id": plan.id,
                "version": plan.version,
                "from_status": decision.from_status,
                "to_status": to_status,
                "reason": reason,
                "required_changes": required_changes,
                "jira_sync_preview": jira_sync_preview,
            },
        )
    )
    await db.flush()
    return {"plan": serialize_change_plan(plan), "decision": serialize_change_plan_decision(decision)}


def _validated_decision(
    plan: WorkChangePlan, payload: dict[str, Any]
) -> tuple[str, str | None, list[str], list[str]]:
    """Return action, reason, required changes and human-verified criteria, or raise the refusal."""
    action = str(payload.get("action") or "").strip().lower()
    if action not in PLAN_DECISIONS:
        raise HTTPException(status_code=422, detail="action must be approve, reject, or request_clarification")
    if plan.status in {"approved", "rejected", "superseded"}:
        raise HTTPException(status_code=409, detail=f"Change Plan is already {plan.status}")
    reason = blank_to_none(payload.get("reason"))
    required_changes = string_list(payload.get("required_changes"))
    if action == "request_clarification" and not required_changes and not reason:
        raise HTTPException(status_code=422, detail="Clarification requests require a reason or required changes")
    human_verified_criteria = string_list(payload.get("human_verified_criteria"))
    if action == "approve":
        coverage_blockers = acceptance_coverage_blockers(
            plan_type=str(dict(plan.evidence_json or {}).get("plan_type") or ""),
            criteria=list(plan.acceptance_criteria_json or []),
            validation_plan=list(plan.validation_plan_json or []),
            has_change_units=bool(plan.change_units_json),
            human_verified_ids=human_verified_criteria,
        )
        if coverage_blockers:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "acceptance_coverage_incomplete",
                    "message": "Approval blocked: acceptance criteria without enforceable validation commands.",
                    "blockers": coverage_blockers,
                },
            )
    return action, reason, required_changes, human_verified_criteria


def _decision_evidence(payload: dict[str, Any], *, action: str, human_verified_criteria: list[str]) -> dict[str, Any]:
    return {
        **object_value(payload.get("evidence")),
        **(
            {"human_verified_criteria": human_verified_criteria}
            if action == "approve" and human_verified_criteria
            else {}
        ),
    }


def _apply_decision(
    plan: WorkChangePlan, *, action: str, to_status: str, actor_id: str, preview: dict[str, Any]
) -> None:
    now = utc_now()
    plan.status = to_status
    plan.updated_by = actor_id
    plan.decided_by = actor_id
    plan.decided_at = now
    plan.jira_sync_preview_json = preview
    if action == "approve":
        plan.approved_by = actor_id
        plan.approved_at = now


async def list_change_plan_decisions(db: AsyncSession, change_plan_id: str) -> list[dict[str, Any]]:
    stmt = (
        select(WorkChangePlanDecision)
        .where(WorkChangePlanDecision.change_plan_id == change_plan_id)
        .order_by(WorkChangePlanDecision.created_at.desc())
    )
    return [serialize_change_plan_decision(row) for row in (await db.execute(stmt)).scalars().all()]


async def work_item_has_approved_change_plan(db: AsyncSession, work_item_id: str) -> bool:
    count = (
        await db.execute(
            select(func.count(WorkChangePlan.id)).where(
                WorkChangePlan.work_item_id == work_item_id,
                WorkChangePlan.status == "approved",
            )
        )
    ).scalar_one()
    return bool(count)
