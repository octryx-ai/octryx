"""Change-plan generation snapshots the work item's change units and reviewers, versions and supersedes an open plan, and a redeclared work item supersedes its plans and units."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, WorkChangePlan, WorkChangePlanDecision
from tests.services.secure_work.secure_work_change_plans_support import (
    _create_repository_profile,
    _create_workflow,
    _plan_change_unit,
    _work_item,
)

#: The repository coding metadata a profile needs before a plan has no open
#: question: without it the plan asks to complete the profile.
_COMPLETE_CODING_PROFILE = {
    "build_commands": ["make build"],
    "test_commands": ["backend/.venv/bin/python -m pytest backend/tests/services/secure_work/test_secure_work_change_plans.py"],
    "lint_commands": ["backend/.venv/bin/python -m ruff check backend/app/services/secure_work"],
    "format_commands": ["make format-check"],
    "package_commands": ["make package"],
    "local_run_commands": ["make run"],
    "protected_paths": ["backend/app/runtime/**"],
    "artifact_paths": ["dist/**"],
    "test_report_paths": ["reports/junit.xml"],
}


async def test_change_plan_generation_snapshots_work_item_change_units_and_reviewers(client, auth_headers, db):
    repo_profile = await _create_repository_profile(client, auth_headers, **_COMPLETE_CODING_PROFILE)
    workflow = await _create_workflow(client, auth_headers)
    item = _work_item()
    db.add(item)
    await db.commit()
    await _plan_change_unit(client, auth_headers, item, repo_profile)

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/change-plans/generate",
        headers=auth_headers,
        json={"workflow_id": workflow["id"], "target_state": "ready_for_review"},
    )

    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["version"] == 1
    assert plan["status"] == "ready_for_review"
    assert plan["open_questions"] == []
    assert plan["work_item_id"] == item.id
    assert plan["affected_repositories"][0]["repository_name"] == "acme-orders-runtime"
    assert plan["change_units"][0]["branch_name"] == "feature/OCX-320-add-approved-change-plan"
    assert plan["validation_plan"][0]["command"].startswith("backend/.venv/bin/python")
    # The repository record's declared default reviewer comes first (owners and Workspace members follow).
    assert plan["reviewer_recommendations"][0]["display_name"] == "alice"
    assert plan["required_approvals"][0]["type"] == "change_plan"
    assert plan["evidence"]["work_item"]["source_key"] == "OCX-320"
    assert plan["jira_sync_preview"]["will_mutate_jira"] is False

    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_type == "work_item",
                AuditLog.resource_id == item.id,
                AuditLog.action == "secure_work.change_plan_generated",
            )
        )
    ).scalar_one()
    assert audit.details["version"] == 1
    assert audit.details["change_plan_id"] == plan["id"]


async def test_change_plan_generation_versions_and_supersedes_open_plan(client, auth_headers, db):
    repo_profile = await _create_repository_profile(client, auth_headers)
    item = _work_item(source_key="OCX-320-V2")
    db.add(item)
    await db.commit()
    await _plan_change_unit(client, auth_headers, item, repo_profile)

    first = (
        await client.post(
            f"/api/v1/secure-work/work-items/{item.id}/change-plans/generate",
            headers=auth_headers,
            json={},
        )
    ).json()
    second_response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/change-plans/generate",
        headers=auth_headers,
        json={"assumptions": ["Second planning pass after repository impact update."]},
    )

    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["version"] == 2
    assert second["supersedes_plan_id"] == first["id"]
    first_row = await db.get(WorkChangePlan, first["id"])
    assert first_row.status == "superseded"


async def test_work_item_redeclare_supersedes_plans_and_units(client, auth_headers, db):
    repo_profile = await _create_repository_profile(client, auth_headers)
    item = _work_item(source_key="OCX-320-REDECLARE")
    db.add(item)
    await db.commit()
    unit = await _plan_change_unit(client, auth_headers, item, repo_profile)
    plan = (
        await client.post(
            f"/api/v1/secure-work/work-items/{item.id}/change-plans/generate",
            headers=auth_headers,
            json={},
        )
    ).json()
    approved = await client.post(
        f"/api/v1/secure-work/change-plans/{plan['id']}/decision",
        headers=auth_headers,
        json={"action": "approve"},
    )
    assert approved.status_code == 200, approved.text

    missing_reason = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/redeclare",
        headers=auth_headers,
        json={},
    )
    assert missing_reason.status_code == 422

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/redeclare",
        headers=auth_headers,
        json={"reason": "PR declined: base/config leftovers", "evidence": {"pr_url": "https://example.test/pr/675"}},
    )
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["superseded_plans"] == 1
    assert summary["superseded_units"] == 1

    plan_row = await db.get(WorkChangePlan, plan["id"])
    assert plan_row.status == "superseded"
    decision = (
        await db.execute(
            select(WorkChangePlanDecision).where(
                WorkChangePlanDecision.change_plan_id == plan["id"],
                WorkChangePlanDecision.action == "redeclare",
            )
        )
    ).scalar_one()
    assert decision.reason == "PR declined: base/config leftovers"

    # A fresh plan no longer snapshots the superseded unit and asks for repositories again.
    fresh = (
        await client.post(
            f"/api/v1/secure-work/work-items/{item.id}/change-plans/generate",
            headers=auth_headers,
            json={},
        )
    ).json()
    assert fresh["change_units"] == []
    assert unit["id"] not in [entry.get("id") for entry in fresh["change_units"]]
    assert any("repository" in question.lower() for question in fresh["open_questions"])
