"""The coding pipeline trace: a normal run completes, a run without delivery evidence is blocked, a no-op closeout needs no pull request, a failed stage asks for action and cancel is audited."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, WorkItemStateEvent
from tests.services.secure_work.secure_work_coding_pipeline_support import (
    _approved_plan_and_unit,
    _create_config,
    _work_item,
)


async def test_coding_pipeline_normal_trace_completed(client, auth_headers, db):
    config = await _create_config(client, auth_headers)
    item = _work_item()
    db.add(item)
    await db.flush()
    plan, unit = await _approved_plan_and_unit(db, item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-pipeline/start",
        headers=auth_headers,
        json={
            "config_id": config["id"],
            "change_plan_id": plan.id,
            "change_unit_ids": [unit.id],
            "changed_files": ["backend/app/services/secure_work/coding_pipelines.py"],
            "stage_results": {
                "intake": {"status": "completed", "evidence": [{"kind": "repo_resolution"}]},
                "policy_preflight": {"status": "completed", "evidence": [{"kind": "policy_preview"}]},
                "implementation": {"status": "completed", "outputs": {"commits": 2}},
                "local_validation": {"status": "completed", "outputs": {"commands": ["npm run build"]}},
                "acceptance_closeout": {
                    "status": "completed",
                    "outputs": {"pr_url": "https://bitbucket.example/projects/OCX/repos/runtime/pull-requests/12"},
                    "evidence": [{"kind": "acceptance"}],
                },
            },
        },
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "completed"
    assert run["summary"]["state_machine"]["phase"] == "completed"
    assert run["summary"]["state_machine"]["evidence"]["pull_request_created"] is True
    assert run["summary"]["counts"]["completed"] == 5
    assert run["summary"]["execution_context"]["change_plan_id"] == plan.id
    assert run["summary"]["execution_context"]["change_unit_ids"] == [unit.id]
    assert [stage["stage_key"] for stage in run["stages"]] == [
        "intake",
        "policy_preflight",
        "implementation",
        "local_validation",
        "acceptance_closeout",
    ]
    await db.refresh(item)
    assert item.work_state == "in_progress"
    state_event = (
        await db.execute(
            select(WorkItemStateEvent).where(
                WorkItemStateEvent.work_item_id == item.id,
                WorkItemStateEvent.from_state == "intake",
                WorkItemStateEvent.to_state == "in_progress",
            )
        )
    ).scalar_one_or_none()
    assert state_event is not None
    assert state_event.source == "coding_pipeline"

    trace_response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/coding-pipeline",
        headers=auth_headers,
    )
    assert trace_response.status_code == 200, trace_response.text
    assert trace_response.json()["run"]["id"] == run["id"]


async def test_coding_pipeline_blocks_completed_run_without_delivery_evidence(client, auth_headers, db):
    config = await _create_config(client, auth_headers)
    item = _work_item(source_key="OCX-333B", title="Prevent fake completion")
    db.add(item)
    await db.flush()
    plan, unit = await _approved_plan_and_unit(db, item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-pipeline/start",
        headers=auth_headers,
        json={
            "config_id": config["id"],
            "change_plan_id": plan.id,
            "change_unit_ids": [unit.id],
            "stage_results": {
                "intake": {"status": "completed", "evidence": [{"kind": "repo_resolution"}]},
                "policy_preflight": {"status": "completed", "evidence": [{"kind": "policy_preview"}]},
                "implementation": {"status": "completed", "outputs": {"commits": 1}},
                "local_validation": {"status": "completed", "outputs": {"commands": ["npm run build"]}},
                "acceptance_closeout": {"status": "completed", "evidence": [{"kind": "acceptance"}]},
            },
        },
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "blocked"
    assert run["control_state"] == "blocked"
    assert run["current_stage_key"] == "blocked"
    state_machine = run["summary"]["state_machine"]
    assert state_machine["version"] == "coding_execution_state_machine.v1"
    assert state_machine["phase"] == "blocked"
    assert state_machine["next_action"]["key"] == "stop_blocked"
    assert state_machine["blockers"][0]["code"] == "delivery_evidence_required"


async def test_coding_pipeline_allows_no_op_closeout_without_pull_request(client, auth_headers, db):
    config = await _create_config(client, auth_headers)
    item = _work_item(source_key="OCX-333C", title="No-op closeout")
    db.add(item)
    await db.flush()
    plan, unit = await _approved_plan_and_unit(db, item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-pipeline/start",
        headers=auth_headers,
        json={
            "config_id": config["id"],
            "change_plan_id": plan.id,
            "change_unit_ids": [unit.id],
            "stage_results": {
                "intake": {"status": "completed", "evidence": [{"kind": "repo_resolution"}]},
                "policy_preflight": {"status": "completed", "evidence": [{"kind": "policy_preview"}]},
                "implementation": {
                    "status": "completed",
                    "outputs": {"no_op_reason": "Approved source already matches the requested state."},
                },
                "local_validation": {"status": "skipped", "evidence": [{"kind": "no_op"}]},
                "acceptance_closeout": {"status": "completed", "evidence": [{"kind": "acceptance"}]},
            },
        },
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "completed"
    assert run["summary"]["state_machine"]["phase"] == "completed"
    assert run["summary"]["state_machine"]["evidence"]["no_op"] is True


async def test_coding_pipeline_failed_stage_required_action(client, auth_headers, db):
    config = await _create_config(client, auth_headers)
    item = _work_item(source_key="OCX-334", title="Fail validation")
    db.add(item)
    await db.flush()
    plan, unit = await _approved_plan_and_unit(db, item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-pipeline/start",
        headers=auth_headers,
        json={
            "config_id": config["id"],
            "change_plan_id": plan.id,
            "change_unit_ids": [unit.id],
            "stage_results": {
                "intake": {"status": "completed"},
                "local_validation": {
                    "status": "failed",
                    "required_actions": ["Fix failing tests and rerun local validation."],
                    "evidence": [{"kind": "test_failure", "command": "npm test"}],
                },
            },
        },
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "failed"
    failed_stage = next(stage for stage in run["stages"] if stage["stage_key"] == "local_validation")
    assert failed_stage["required_actions"] == ["Fix failing tests and rerun local validation."]


async def test_coding_pipeline_cancel_control_audits(client, auth_headers, db):
    config = await _create_config(client, auth_headers)
    item = _work_item(source_key="OCX-335", title="Cancel run")
    db.add(item)
    await db.flush()
    plan, unit = await _approved_plan_and_unit(db, item)
    await db.commit()

    start_response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-pipeline/start",
        headers=auth_headers,
        json={"config_id": config["id"], "change_plan_id": plan.id, "change_unit_ids": [unit.id]},
    )
    run_id = start_response.json()["id"]
    cancel_response = await client.post(
        f"/api/v1/secure-work/coding-pipeline-runs/{run_id}/control",
        headers=auth_headers,
        json={"action": "cancel"},
    )

    assert cancel_response.status_code == 200, cancel_response.text
    assert cancel_response.json()["status"] == "cancelled"
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == "secure_work.coding_pipeline_cancel",
                AuditLog.resource_id == item.id,
            )
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.details["run_id"] == run_id
