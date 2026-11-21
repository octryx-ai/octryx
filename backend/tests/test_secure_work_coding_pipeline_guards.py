"""The coding pipeline guards: policy blocks, a missing approved change plan, out-of-scope changed files and a stale source after the approved plan stop the run."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import AuditLog, WorkChangePlan, WorkItemStateEvent
from app.time_utils import utc_now
from tests.secure_work_coding_pipeline_support import _approved_plan_and_unit, _create_config, _work_item


async def test_coding_pipeline_policy_blocked_trace(client, auth_headers, db):
    config = await _create_config(client, auth_headers)
    item = _work_item(source_key="OCX-336", title="Policy blocked")
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
                "policy_preflight": {
                    "status": "policy_blocked",
                    "policy_refs": [{"policy": "protected_path"}],
                    "required_actions": ["Request security approval before implementation."],
                }
            },
        },
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "policy_blocked"
    assert run["current_stage_key"] == "policy_preflight"
    blocked = next(stage for stage in run["stages"] if stage["stage_key"] == "policy_preflight")
    assert blocked["policy_refs"] == [{"policy": "protected_path"}]
    assert run["summary"]["required_actions"] == ["Request security approval before implementation."]


async def test_coding_pipeline_requires_approved_change_plan(client, auth_headers, db):
    config = await _create_config(client, auth_headers)
    item = _work_item(source_key="OCX-337", title="Missing approved plan")
    db.add(item)
    await db.flush()
    _, unit = await _approved_plan_and_unit(db, item)
    plan = (await db.execute(select(WorkChangePlan).where(WorkChangePlan.work_item_id == item.id))).scalar_one()
    plan.status = "ready_for_review"
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-pipeline/start",
        headers=auth_headers,
        json={"config_id": config["id"], "change_plan_id": plan.id, "change_unit_ids": [unit.id]},
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "policy_blocked"
    assert run["summary"]["execution_context"]["blockers"][0]["code"] == "approved_change_plan_required"
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == "secure_work.coding_pipeline_policy_blocked",
                AuditLog.resource_id == item.id,
            )
        )
    ).scalar_one()
    assert audit.details["blockers"][0]["code"] == "approved_change_plan_required"
    await db.refresh(item)
    assert item.work_state == "needs_human_review"


async def test_coding_pipeline_blocks_out_of_scope_changed_files(client, auth_headers, db):
    config = await _create_config(client, auth_headers)
    item = _work_item(source_key="OCX-338", title="Out of scope change")
    db.add(item)
    await db.flush()
    plan, unit = await _approved_plan_and_unit(db, item, expected_paths=["backend/app/services/secure_work"])
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-pipeline/start",
        headers=auth_headers,
        json={
            "config_id": config["id"],
            "change_plan_id": plan.id,
            "change_unit_ids": [unit.id],
            "changed_files": ["frontend/chat/src/App.tsx"],
        },
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "policy_blocked"
    blocked = next(stage for stage in run["stages"] if stage["stage_key"] == "policy_preflight")
    assert blocked["policy_refs"][0]["code"] == "out_of_scope_files"
    assert blocked["policy_refs"][0]["files"] == ["frontend/chat/src/App.tsx"]
    await db.refresh(item)
    assert item.work_state == "needs_human_review"


async def test_coding_pipeline_blocks_stale_source_after_approved_plan(client, auth_headers, db):
    config = await _create_config(client, auth_headers)
    item = _work_item(source_key="OCX-339", title="Source changed after approval")
    db.add(item)
    await db.flush()
    plan, unit = await _approved_plan_and_unit(db, item)
    item.last_source_updated_at = utc_now() + timedelta(minutes=5)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/coding-pipeline/start",
        headers=auth_headers,
        json={"config_id": config["id"], "change_plan_id": plan.id, "change_unit_ids": [unit.id]},
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "policy_blocked"
    blocker = run["summary"]["execution_context"]["blockers"][0]
    assert blocker["code"] == "source_changed_after_plan"
    assert blocker["source_evidence"]["last_source_updated_at"]
    await db.refresh(item)
    assert item.work_state == "needs_replan"
    state_event = (
        await db.execute(
            select(WorkItemStateEvent).where(
                WorkItemStateEvent.work_item_id == item.id,
                WorkItemStateEvent.to_state == "needs_replan",
            )
        )
    ).scalar_one_or_none()
    assert state_event is not None
    assert state_event.conflict_json["blockers"][0]["code"] == "source_changed_after_plan"
