"""The HTTP gate report and change-plan gate follow the latest plan state, a required review blocks opening a PR, persisted evaluations store the corrected gates, and an explicit operator result passes only its gate."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkChangePlan, WorkCodingAuditEvent, WorkItem
from tests.secure_work_coding_audit_support import _admin_id, _coding_item

# ---- HTTP report, readiness and persisted evaluation -------------------------------------------

async def _plan_only_item(db, admin_id, *, plan_status="approved", version=1):
    item = WorkItem(
        source_type="jira", source_instance="gate-evidence-test", source_key=f"OCX-1128-{plan_status}",
        source_project_key="OCX", title="Plan only", source_status="In Progress", work_state="in_progress",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    db.add(WorkChangePlan(
        work_item_id=item.id, version=version, status=plan_status, title="Plan",
        validation_plan_json=[{"command": "pytest tests/test_password.py", "status": "passed"}],
        evidence_json={"summary": "all tests passed"}, created_by=admin_id,
    ))
    await db.commit()
    return item


async def _two_plan_item(db, admin_id, v1_status, v2_status):
    item = WorkItem(
        source_type="jira", source_instance="gate-evidence-test", source_key=f"OCX-1128-{v1_status}-{v2_status}",
        source_project_key="OCX", title="Two plan versions", source_status="In Progress", work_state="in_progress",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    for version, status in ((1, v1_status), (2, v2_status)):
        db.add(WorkChangePlan(
            work_item_id=item.id, version=version, status=status, title=f"Plan v{version}", created_by=admin_id,
            approved_by=admin_id if status == "approved" else None,
        ))
    await db.commit()
    return item


async def test_http_report_for_a_plan_only_item_is_missing_and_not_ready(client, auth_headers, db):
    item = await _plan_only_item(db, await _admin_id(db))
    response = await client.get(f"/api/v1/secure-work/work-items/{item.id}/coding-audit", headers=auth_headers)
    assert response.status_code == 200, response.text
    report = response.json()
    gates = {gate["key"]: gate for gate in report["quality_gates"]}
    for key in ("local_tests", "lint", "dependency_audit", "trivy_security_scan", "ci_status"):
        assert gates[key]["status"] == "missing", key
        assert set(gates[key]) == {"key", "label", "status", "blocking", "reason", "evidence"}, "HTTP gate fields kept"
    assert report["pr_summary"]["tests"] == [], "planned checks are never listed as tests"
    assert report["pr_summary"]["ready_to_open_pr"] is False


async def test_http_change_plan_gate_names_the_actual_latest_plan_state(client, auth_headers, db):
    item = await _plan_only_item(db, await _admin_id(db), plan_status="needs_clarification", version=2)
    report = (await client.get(f"/api/v1/secure-work/work-items/{item.id}/coding-audit", headers=auth_headers)).json()
    gate = next(gate for gate in report["quality_gates"] if gate["key"] == "change_plan")
    assert gate["status"] == "missing"
    assert gate["reason"] == "No approved Change Plan. Latest plan v2 is needs clarification."
    assert gate["evidence"]["plan_status"] == "needs_clarification"


@pytest.mark.parametrize(
    ("v1", "v2", "status", "reason"),
    [
        ("approved", "needs_clarification", "missing",
         "No approved Change Plan. Latest plan v2 is needs clarification. The earlier approval of v1 does not cover the latest plan."),
        ("approved", "rejected", "missing",
         "No approved Change Plan. Latest plan v2 is rejected. The earlier approval of v1 does not cover the latest plan."),
        ("approved", "ready_for_review", "review_required",
         "Latest Change Plan v2 is ready for review and not approved yet. The earlier approval of v1 does not cover the latest plan."),
        ("rejected", "approved", "pass", "Latest Change Plan v2 is approved."),
    ],
)
async def test_http_change_plan_gate_is_decided_by_the_latest_version(client, auth_headers, db, v1, v2, status, reason):
    item = await _two_plan_item(db, await _admin_id(db), v1, v2)
    report = (await client.get(f"/api/v1/secure-work/work-items/{item.id}/coding-audit", headers=auth_headers)).json()
    gate = next(gate for gate in report["quality_gates"] if gate["key"] == "change_plan")
    assert (gate["status"], gate["reason"]) == (status, reason)
    if status != "pass":
        assert gate["evidence"]["version"] == 2


async def test_http_review_required_gate_is_not_ready_to_open_a_pr(client, auth_headers, db):
    item = await _coding_item(db, await _admin_id(db))
    db.add(WorkCodingAuditEvent(work_item_id=item.id, event_type="local_validation", title="Lint", actor_kind="system",
                                gate_results_json=[{"key": "lint", "status": "pending"}]))
    await db.commit()
    report = (await client.get(f"/api/v1/secure-work/work-items/{item.id}/coding-audit", headers=auth_headers)).json()
    lint = next(gate for gate in report["quality_gates"] if gate["key"] == "lint")
    assert lint["status"] == "review_required"
    assert report["quality_summary"]["blocking"] == 0, "blocking count semantics are unchanged"
    assert report["pr_summary"]["ready_to_open_pr"] is False, "a gate that needs review is not ready"


async def test_persisted_evaluation_stores_the_corrected_gates_and_is_not_reused(client, auth_headers, db):
    item = await _plan_only_item(db, await _admin_id(db))
    evaluated = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-quality-gates/evaluate", headers=auth_headers, json={}
    )
    assert evaluated.status_code == 200, evaluated.text
    persisted = (
        await db.execute(select(WorkCodingAuditEvent).where(
            WorkCodingAuditEvent.work_item_id == item.id,
            WorkCodingAuditEvent.event_type == "quality_gate_evaluation",
        ))
    ).scalar_one()
    stored = {gate["key"]: gate["status"] for gate in persisted.gate_results_json}
    assert stored["local_tests"] == "missing"
    again = (await client.get(f"/api/v1/secure-work/work-items/{item.id}/coding-audit", headers=auth_headers)).json()
    assert next(gate for gate in again["quality_gates"] if gate["key"] == "local_tests")["status"] == "missing"


async def test_http_explicit_operator_gate_result_passes_only_its_gate(client, auth_headers, db):
    item = await _plan_only_item(db, await _admin_id(db))
    posted = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-audit/events",
        headers=auth_headers,
        json={
            "event_type": "dependency_scan",
            "title": "Dependency audit",
            "summary": "Local tests passed too (free text, not a result).",
            "gate_results": [{"key": "dependency_audit", "status": "passed"}],
        },
    )
    assert posted.status_code == 200, posted.text
    report = (await client.get(f"/api/v1/secure-work/work-items/{item.id}/coding-audit", headers=auth_headers)).json()
    gates = {gate["key"]: gate["status"] for gate in report["quality_gates"]}
    assert gates["dependency_audit"] == "pass"
    assert gates["local_tests"] == "missing"
