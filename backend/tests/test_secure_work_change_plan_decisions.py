"""Change-plan decisions: an approval is audited and runs the Jira sync hook, a clarification needs a reason or changes, and approval is blocked while a criterion has no command."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, WorkChangePlan, WorkChangePlanDecision
from tests.secure_work_change_plans_support import (
    _create_repository_profile,
    _create_workflow,
    _plan_change_unit,
    _work_item,
)


async def test_change_plan_decision_approves_and_audits_jira_sync_hook(client, auth_headers, db):
    repo_profile = await _create_repository_profile(client, auth_headers)
    workflow = await _create_workflow(client, auth_headers)
    item = _work_item(source_key=("OCX-" + "320-APPROVE"))
    db.add(item)
    await db.commit()
    await _plan_change_unit(client, auth_headers, item, repo_profile)
    plan = (
        await client.post(
            f"/api/v1/secure-work/work-items/{item.id}/change-plans/generate",
            headers=auth_headers,
            json={"workflow_id": workflow["id"]},
        )
    ).json()

    response = await client.post(
        f"/api/v1/secure-work/change-plans/{plan['id']}/decision",
        headers=auth_headers,
        json={
            "action": "approve",
            "workflow_id": workflow["id"],
            "target_state": "approved",
            "reason": "Plan is complete and reviewers are known.",
            "evidence": {"source": "unit-test"},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["plan"]["status"] == "approved"
    assert payload["plan"]["approved_by"]
    assert payload["decision"]["action"] == "approve"
    assert payload["decision"]["jira_sync_preview"]["target_status"] == "Ready for Development"
    assert payload["decision"]["jira_sync_preview"]["will_mutate_jira"] is False

    decision = (
        await db.execute(select(WorkChangePlanDecision).where(WorkChangePlanDecision.change_plan_id == plan["id"]))
    ).scalar_one()
    assert decision.to_status == "approved"

    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_type == "work_item",
                AuditLog.resource_id == item.id,
                AuditLog.action == "secure_work.change_plan_approve",
            )
        )
    ).scalar_one()
    assert audit.details["jira_sync_preview"]["target_status"] == "Ready for Development"


async def test_change_plan_clarification_requires_reason_or_changes(client, auth_headers, db):
    item = _work_item(source_key=("OCX-" + "320-CLARIFY"))
    db.add(item)
    await db.commit()
    plan = (
        await client.post(
            f"/api/v1/secure-work/work-items/{item.id}/change-plans/generate",
            headers=auth_headers,
            json={"open_questions": ["Which repository should change?"]},
        )
    ).json()

    invalid = await client.post(
        f"/api/v1/secure-work/change-plans/{plan['id']}/decision",
        headers=auth_headers,
        json={"action": "request_clarification"},
    )
    assert invalid.status_code == 422

    valid = await client.post(
        f"/api/v1/secure-work/change-plans/{plan['id']}/decision",
        headers=auth_headers,
        json={"action": "request_clarification", "required_changes": ["Select repository profile."]},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["plan"]["status"] == "needs_clarification"
    assert valid.json()["decision"]["required_changes"] == ["Select repository profile."]


async def test_change_plan_approval_blocked_when_criterion_has_no_command(client, auth_headers, db):
    repo_profile = await _create_repository_profile(client, auth_headers)
    item = _work_item(source_key="OCX-320-COVERAGE")
    db.add(item)
    await db.commit()
    await _plan_change_unit(client, auth_headers, item, repo_profile)
    plan = (
        await client.post(
            f"/api/v1/secure-work/work-items/{item.id}/change-plans/generate",
            headers=auth_headers,
            json={
                "acceptance_criteria": [
                    {
                        "id": "AC1",
                        "text": "Remove executed removed/moved blocks",
                        "validation_commands": [
                            "backend/.venv/bin/python -m pytest backend/tests/test_secure_work_change_plans.py"
                        ],
                    },
                    {"id": "AC2", "text": "Clean also the config for prod and nonprod"},
                ]
            },
        )
    ).json()
    assert [entry["id"] for entry in plan["acceptance_criteria"]] == ["AC1", "AC2"]

    blocked = await client.post(
        f"/api/v1/secure-work/change-plans/{plan['id']}/decision",
        headers=auth_headers,
        json={"action": "approve"},
    )
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert detail["error"] == "acceptance_coverage_incomplete"
    assert any("AC2" in blocker for blocker in detail["blockers"])
    plan_row = await db.get(WorkChangePlan, plan["id"])
    assert plan_row.status == plan["status"]  # the blocked decision must not change the plan
    assert plan_row.status != "approved"

    approved = await client.post(
        f"/api/v1/secure-work/change-plans/{plan['id']}/decision",
        headers=auth_headers,
        json={"action": "approve", "human_verified_criteria": ["AC2"], "reason": "Config checked by hand."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["decision"]["evidence"]["human_verified_criteria"] == ["AC2"]
