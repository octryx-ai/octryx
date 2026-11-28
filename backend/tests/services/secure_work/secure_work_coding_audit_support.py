"""Shared helpers for the test_secure_work_coding_audit_* modules."""

from __future__ import annotations

from sqlalchemy import select

from app.models import (
    User,
    WorkChangePlan,
    WorkCodingAuditEvent,
    WorkCodingPipelineRun,
    WorkCodingPipelineStage,
    WorkCodingReviewEvent,
    WorkItem,
    WorkItemChangeUnit,
)
from app.time_utils import utc_now


async def _admin_id(db) -> str:
    return (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()


def _add_change_unit(db, item: WorkItem, admin_id: str) -> WorkItemChangeUnit:
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_name="octryx-api",
        branch_name="feature/corp-335-audit",
        scope="Persist audit report and quality gates",
        expected_paths_json=["backend/app/services/secure_work/coding_audit.py"],
        validation_commands_json=["backend/.venv/bin/python -m pytest backend/tests/services/secure_work/test_secure_work_coding_audit.py"],
        reviewer_policy_json={"required_roles": ["operation"]},
        pr_link="https://bitbucket.example.test/projects/OCX/repos/api/pull-requests/335",
        status="validated",
        created_by=admin_id,
    )
    db.add(unit)
    return unit


def _add_approved_plan(db, item: WorkItem, admin_id: str) -> WorkChangePlan:
    plan = WorkChangePlan(
        work_item_id=item.id,
        version=1,
        status="approved",
        title="OCX-335 audit plan",
        understood_request="Make coding work audit-ready with PR quality gates.",
        validation_plan_json=[{"command": "pytest", "status": "passed"}],
        security_risks_json=[],
        evidence_json={"approach": "service-owned gate evaluation"},
        created_by=admin_id,
        approved_by=admin_id,
        decided_by=admin_id,
    )
    db.add(plan)
    return plan


async def _add_completed_pipeline_run(db, item: WorkItem, admin_id: str) -> None:
    run = WorkCodingPipelineRun(
        work_item_id=item.id,
        status="completed",
        control_state="completed",
        summary_json={"result": "ready"},
        started_by=admin_id,
    )
    db.add(run)
    await db.flush()
    db.add_all(
        [
            WorkCodingPipelineStage(
                run_id=run.id,
                stage_key="policy_preflight",
                label="Policy preflight",
                stage_order=1,
                status="completed",
                evidence_json=[{"kind": "coding_policy_preview", "status": "passed"}],
            ),
            WorkCodingPipelineStage(
                run_id=run.id,
                stage_key="local_validation",
                label="Local validation",
                stage_order=2,
                status="completed",
                evidence_json=[{"command": "pytest", "status": "passed"}],
            ),
        ]
    )


async def _add_review_decisions(
    db, item: WorkItem, unit: WorkItemChangeUnit, plan: WorkChangePlan, admin_id: str
) -> None:
    # Legacy feedback with "approved" prose and status: activity only, never an approval.
    db.add(
        WorkCodingReviewEvent(
            work_item_id=item.id,
            event_type="review_decision",
            file_path="backend/app/services/secure_work/coding_audit.py",
            severity="info",
            status="approved",
            body="Approved for PR after audit review.",
            created_by=admin_id,
        )
    )
    await db.flush()
    # The explicit decision the producer records: bound to the latest plan and this unit's state.
    db.add(
        WorkCodingReviewEvent(
            work_item_id=item.id,
            change_unit_id=unit.id,
            event_type="review_decision",
            file_path="",
            status="approved",
            body="",
            metadata_json={
                "review_decision_record": {
                    "schema": "coding_review_decision.v1",
                    "decision": "approved",
                    "actor_id": admin_id,
                    "change_plan_id": plan.id,
                    "plan_version": plan.version,
                    "scope": "change_unit",
                    "change_unit_id": unit.id,
                    "change_unit_marker": unit.updated_at.isoformat(),
                    "recorded_at": utc_now().isoformat(),
                }
            },
            created_by=admin_id,
        )
    )


async def _coding_item(db, admin_id: str) -> WorkItem:
    item = WorkItem(
        source_type="jira",
        source_instance="coding-audit-test",
        source_key="OCX-335",
        source_project_key="OCX",
        title="Audit governed coding work",
        description="Implement an audit-ready coding workflow.",
        source_status="In Review",
        work_state="review_ready",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    # Recorded results count only when they name their gate explicitly.
    db.add(WorkCodingAuditEvent(
        work_item_id=item.id, event_type="local_validation", title="Local validation", actor_kind="system",
        gate_results_json=[{"key": key, "status": "passed"} for key in (
            "local_tests", "lint", "dependency_audit", "trivy_security_scan", "ci_status")],
    ))
    unit = _add_change_unit(db, item, admin_id)
    plan = _add_approved_plan(db, item, admin_id)
    await _add_completed_pipeline_run(db, item, admin_id)
    await _add_review_decisions(db, item, unit, plan, admin_id)
    await db.commit()
    return item
