"""The coding audit report evaluates quality gates, ignores stale gate evaluations and risk text, and blocks stale approved change plans and PR readiness without evidence."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import WorkChangePlan, WorkCodingAuditEvent, WorkItem, WorkItemChangeUnit
from app.time_utils import utc_now
from tests.services.secure_work.secure_work_coding_audit_support import _admin_id, _coding_item


async def test_coding_audit_report_and_quality_gate_evaluation(client, auth_headers, db):
    admin_id = await _admin_id(db)
    item = await _coding_item(db, admin_id)

    event_response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-audit/events",
        headers=auth_headers,
        json={
            "event_type": "local_validation",
            "title": "Local validation passed",
            "summary": "pytest, ruff, npm audit, and trivy were captured as evidence.",
            "repository_name": "octryx-api",
            "branch_name": "feature/corp-335-audit",
            "commit_sha": "abc1234",
            "pr_url": "https://bitbucket.example.test/projects/OCX/repos/api/pull-requests/335",
            "evidence": {"commands": ["pytest", "ruff", "npm audit", "trivy"]},
        },
    )
    assert event_response.status_code == 200, event_response.text

    report_response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/coding-audit",
        headers=auth_headers,
    )
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()
    assert report["quality_summary"]["status"] == "passed"
    assert report["quality_summary"]["blocking"] == 0
    assert {gate["key"] for gate in report["quality_gates"]} >= {
        "change_plan",
        "local_tests",
        "lint",
        "dependency_audit",
        "trivy_security_scan",
        "ci_status",
        "reviewer_approval",
        "policy_status",
    }
    assert report["pr_summary"]["ready_to_open_pr"] is True
    assert "octryx-api" in report["pr_summary"]["repositories"]
    assert any(event["kind"] == "audit_event" for event in report["timeline"])

    evaluation_response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-quality-gates/evaluate",
        headers=auth_headers,
        json={"evidence": {"source": "test"}},
    )
    assert evaluation_response.status_code == 200, evaluation_response.text
    evaluation = evaluation_response.json()
    assert evaluation["audit_event"]["event_type"] == "quality_gate_evaluation"
    assert evaluation["audit_event"]["gate_results"]
    assert any(event["title"] == "PR quality gates evaluated" for event in evaluation["timeline"])
    assert evaluation["evidence"]["audit_event_count"] == report["evidence"]["audit_event_count"] + 1

    persisted = (
        await db.execute(
            select(WorkCodingAuditEvent).where(
                WorkCodingAuditEvent.work_item_id == item.id,
                WorkCodingAuditEvent.event_type == "quality_gate_evaluation",
            )
        )
    ).scalars().all()
    assert len(persisted) == 1


async def test_coding_audit_ignores_stale_gate_evaluations_and_risk_text(client, auth_headers, db):
    admin_id = await _admin_id(db)
    item = WorkItem(
        source_type="jira",
        source_instance="coding-audit-test",
        source_key="OCX-336",
        source_project_key="OCX",
        title="Avoid recursive gate contamination",
        source_status="In Progress",
        work_state="in_progress",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    db.add(
        WorkItemChangeUnit(
            work_item_id=item.id,
            repository_name="octryx-api",
            branch_name="feature/corp-336-audit",
            scope="Validate gate evidence isolation",
            expected_paths_json=["backend/app/services/secure_work/coding_audit.py"],
            validation_commands_json=["backend/.venv/bin/python -m pytest backend/tests/services/secure_work/test_secure_work_coding_audit.py"],
            reviewer_policy_json={},
            status="validated",
            created_by=admin_id,
        )
    )
    db.add(
        WorkChangePlan(
            work_item_id=item.id,
            version=1,
            status="approved",
            title="OCX-336 audit plan",
            understood_request="Ensure quality gates do not reuse stale gate output.",
            validation_plan_json=[{"command": "pytest backend/tests/services/secure_work/test_secure_work_coding_audit.py", "status": "passed"}],
            security_risks_json=[
                {
                    "severity": "low",
                    "risk": "Could remove active resources if not carefully tested.",
                    "evidence": "Risk text mentions tests but is not validation evidence.",
                }
            ],
            evidence_json={},
            created_by=admin_id,
            approved_by=admin_id,
            decided_by=admin_id,
        )
    )
    db.add(
        WorkCodingAuditEvent(
            work_item_id=item.id,
            event_type="quality_gate_evaluation",
            title="Old quality gate evaluation",
            summary="A stale blocked evaluation must not poison the next report.",
            gate_results_json=[
                {
                    "key": "local_tests",
                    "status": "block",
                    "blocking": True,
                    "reason": "stale result",
                    "evidence": {},
                }
            ],
            actor_id=admin_id,
        )
    )
    await db.commit()

    response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/coding-audit",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    local_tests = next(gate for gate in response.json()["quality_gates"] if gate["key"] == "local_tests")
    # The stale blocked snapshot does not poison the report, and the plan's "passed" check and the
    # unit's planned command are intent, not results: no recorded result, so missing.
    assert local_tests["status"] == "missing"
    assert local_tests["evidence"]["planned_checks"] == 2
    assert "not results" in local_tests["reason"]


async def test_coding_audit_blocks_stale_approved_change_plan(client, auth_headers, db):
    admin_id = await _admin_id(db)
    item = await _coding_item(db, admin_id)
    plan = (
        await db.execute(
            select(WorkChangePlan).where(
                WorkChangePlan.work_item_id == item.id,
                WorkChangePlan.status == "approved",
            )
        )
    ).scalar_one()
    plan.approved_at = utc_now()
    item.last_source_updated_at = plan.approved_at + timedelta(minutes=5)
    await db.commit()

    response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/coding-audit",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    report = response.json()
    change_plan_gate = next(gate for gate in report["quality_gates"] if gate["key"] == "change_plan")
    assert change_plan_gate["status"] == "block"
    assert change_plan_gate["blocking"] is True
    assert change_plan_gate["evidence"]["code"] == "source_changed_after_plan"
    assert report["pr_summary"]["ready_to_open_pr"] is False


async def test_coding_audit_missing_evidence_blocks_pr_readiness(client, auth_headers, db):
    item = WorkItem(
        source_type="jira",
        source_instance="coding-audit-test",
        source_key="OCX-335-MISSING",
        source_project_key="OCX",
        title="Missing validation evidence",
        source_status="Open",
        work_state="planned",
        sync_state="imported",
    )
    db.add(item)
    await db.commit()

    response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/coding-audit",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["quality_summary"]["status"] == "blocked"
    assert report["quality_summary"]["blocking"] > 0
    assert report["pr_summary"]["ready_to_open_pr"] is False
    assert any(gate["status"] == "missing" for gate in report["quality_gates"])
