"""CI/CD findings move a work item to needs-remediation, satisfy the CI quality gate, stay visible on rerun and are ignored when stale."""

from __future__ import annotations

from sqlalchemy import select

from app.models import WorkCicdFinding, WorkCodingAuditEvent, WorkItemStateEvent
from tests.secure_work_cicd_providers_support import _create_provider, _work_item


async def test_cicd_failure_finding_moves_work_item_to_needs_remediation(client, auth_headers, db):
    provider = await _create_provider(client, auth_headers)
    item = _work_item(source_key="OCX-339", title="Feed CI/CD findings", work_state="testing")
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/cicd-findings",
        headers=auth_headers,
        json={
            "provider_config_id": provider["id"],
            "title": "Jenkins build failed",
            "event_status": "failed",
            "job_name": "acme-orders/api-main",
            "build_number": "21",
            "build_url": "https://jenkins/job/acme-orders/job/api-main/21/",
            "branch_name": "feature/corp-339-findings",
            "commit_sha": "fail123",
            "summary": "Compile stage failed.",
            "artifacts": [{"file_name": "compile.log", "relative_path": "logs/compile.log"}],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "current"
    assert body["event_status"] == "failed"
    assert body["state_transition"]["to_state"] == "needs_remediation"

    await db.refresh(item)
    assert item.work_state == "needs_remediation"
    event = (
        await db.execute(select(WorkItemStateEvent).where(WorkItemStateEvent.work_item_id == item.id))
    ).scalar_one()
    assert event.source == "cicd_finding"
    audit_event = (
        await db.execute(select(WorkCodingAuditEvent).where(WorkCodingAuditEvent.work_item_id == item.id))
    ).scalar_one()
    assert audit_event.event_type == "cicd_finding"
    assert audit_event.gate_results_json[0]["status"] == "block"


async def test_cicd_success_finding_satisfies_ci_quality_gate(client, auth_headers, db):
    provider = await _create_provider(client, auth_headers)
    item = _work_item(source_key="OCX-339A", title="Pass CI/CD gate", work_state="testing")
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/cicd-findings",
        headers=auth_headers,
        json={
            "provider_config_id": provider["id"],
            "title": "Jenkins build passed",
            "event_status": "success",
            "job_name": "acme-orders/api-main",
            "build_number": "22",
            "commit_sha": "pass123",
            "evidence": {"test_report": {"total_count": 128, "fail_count": 0}},
        },
    )
    assert response.status_code == 200, response.text

    audit_response = await client.get(f"/api/v1/secure-work/work-items/{item.id}/coding-audit", headers=auth_headers)
    assert audit_response.status_code == 200, audit_response.text
    ci_gate = next(gate for gate in audit_response.json()["quality_gates"] if gate["key"] == "ci_status")
    assert ci_gate["status"] == "pass"
    assert ci_gate["blocking"] is False


async def test_cicd_rerun_finding_is_visible_without_state_change(client, auth_headers, db):
    provider = await _create_provider(client, auth_headers)
    item = _work_item(source_key="OCX-339B", title="Record rerun finding", work_state="testing")
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/cicd-findings",
        headers=auth_headers,
        json={
            "provider_config_id": provider["id"],
            "title": "Jenkins rerun requested",
            "event_status": "rerun_requested",
            "job_name": "acme-orders/api-main",
            "build_number": "23",
            "commit_sha": "rerun123",
            "comments": [{"author": "jenkins", "body": "Rerun triggered after flaky test."}],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["finding_type"] == "rerun"

    list_response = await client.get(f"/api/v1/secure-work/work-items/{item.id}/cicd-findings", headers=auth_headers)
    assert list_response.status_code == 200, list_response.text
    payload = list_response.json()
    assert payload["items"][0]["event_status"] == "rerun_requested"
    assert payload["items"][0]["comments"][0]["body"] == "Rerun triggered after flaky test."
    await db.refresh(item)
    assert item.work_state == "testing"


async def test_cicd_stale_failure_is_audited_but_ignored_by_current_gate(client, auth_headers, db):
    provider = await _create_provider(client, auth_headers)
    item = _work_item(
        source_key="OCX-339C",
        title="Ignore stale CI/CD finding",
        work_state="testing",
        source_fields_json={"current_commit_sha": "new456"},
    )
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/cicd-findings",
        headers=auth_headers,
        json={
            "provider_config_id": provider["id"],
            "title": "Old Jenkins build failed",
            "event_status": "failed",
            "job_name": "acme-orders/api-main",
            "build_number": "20",
            "commit_sha": "old123",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "stale_ignored"
    assert body["current_for_commit"] is False
    assert "new456" in body["stale_reason"]

    await db.refresh(item)
    assert item.work_state == "testing"
    assert (
        await db.execute(select(WorkItemStateEvent).where(WorkItemStateEvent.work_item_id == item.id))
    ).scalar_one_or_none() is None
    assert (
        await db.execute(select(WorkCicdFinding).where(WorkCicdFinding.work_item_id == item.id))
    ).scalar_one().status == "stale_ignored"

    audit_response = await client.get(f"/api/v1/secure-work/work-items/{item.id}/coding-audit", headers=auth_headers)
    ci_gate = next(gate for gate in audit_response.json()["quality_gates"] if gate["key"] == "ci_status")
    assert ci_gate["status"] == "missing"
