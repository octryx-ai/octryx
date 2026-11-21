"""Starting a Work item's coding agent execution: the governed session, the capped model-visible context, the explicit runtime control inventory and the block on a stale plan."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import (
    AuditLog,
    Session,
    WorkCodingAuditEvent,
    WorkCodingPipelineRun,
    WorkCodingPipelineStage,
    WorkCodingWorkspace,
)
from app.services.secure_work.coding.coding_execution import start_work_item_coding_agent_execution
from app.services.secure_work.coding.coding_runtime_contract import coding_runtime_control_inventory
from tests.secure_work_coding_execution_support import _actor, _approved_plan_and_unit, _work_item


def _assert_governed_prompt(captured: dict) -> None:
    assert captured["agent_type"] == "coding"
    # The governed run names its workflow; routing never infers it from this prompt.
    assert captured["platform_workflow_service"] == "secure_work_coding_execution"
    assert "ACME-615" in captured["prompt"]
    assert "aws-shop-infrastructure" in captured["prompt"]
    assert "terraform/base" in captured["prompt"]
    assert "terraform validate" in captured["prompt"]
    assert "Runtime state machine:" in captured["prompt"]
    assert "current_phase: inspected" in captured["prompt"]
    assert "next_required_action: inspect_scope" in captured["prompt"]
    assert "Runtime execution contract:" in captured["prompt"]
    assert "completion_source: runtime_state_machine" in captured["prompt"]
    assert "completion_allowed_when: pull_request_recorded" in captured["prompt"]
    assert "Do not finalize as completed unless" not in captured["prompt"]
    assert "Prepared coding workspaces:" in captured["prompt"]
    assert "apply_patch_workspace" in captured["prompt"]
    assert "commit_and_push_repository_branch" in captured["prompt"]
    assert "create_bitbucket_pull_request" in captured["prompt"]
    assert captured["session_metadata_patch"]["coding_workspace_records"][0]["repository_slug"] == (
        "aws-shop-infrastructure"
    )


async def _assert_start_audit_rows(db, item, plan, result: dict) -> None:
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == "secure_work.coding_agent_execution_started",
                AuditLog.resource_id == item.id,
            )
        )
    ).scalar_one()
    assert audit.details["session_id"] == result["session"]["id"]
    event = (
        await db.execute(
            select(WorkCodingAuditEvent).where(
                WorkCodingAuditEvent.work_item_id == item.id,
                WorkCodingAuditEvent.event_type == "agent_execution_started",
            )
        )
    ).scalar_one()
    assert event.evidence_json["change_plan_id"] == plan.id
    assert event.evidence_json["workspaces"][0]["repository_slug"] == "aws-shop-infrastructure"


async def _assert_prepared_workspace_and_pipeline(db, item, plan, unit, result: dict) -> None:
    workspace = (
        await db.execute(
            select(WorkCodingWorkspace).where(
                WorkCodingWorkspace.work_item_id == item.id,
                WorkCodingWorkspace.pipeline_run_id == result["pipeline_run"]["id"],
                WorkCodingWorkspace.change_unit_id == unit.id,
            )
        )
    ).scalar_one()
    assert workspace.status == "prepared_empty"
    assert workspace.feature_branch == unit.branch_name
    assert workspace.repository_slug == "aws-shop-infrastructure"
    assert workspace.source_evidence_cutoff == plan.approved_at
    assert workspace.session_id == result["session"]["id"]
    pipeline_run = await db.get(WorkCodingPipelineRun, result["pipeline_run"]["id"])
    assert pipeline_run is not None
    assert pipeline_run.summary_json["workspaces"][0]["id"] == workspace.id
    assert pipeline_run.summary_json["agent_session"]["session_id"] == result["session"]["id"]
    assert pipeline_run.summary_json["state_machine"]["phase"] == "inspected"
    assert pipeline_run.summary_json["state_machine"]["next_action"]["key"] == "inspect_scope"
    assert pipeline_run.summary_json["coding_execution_contract"]["version"] == "coding_execution_contract.v1"
    assert pipeline_run.summary_json["coding_execution_contract"]["completion_source"] == "runtime_state_machine"
    assert "state_machine_completion_contract" in pipeline_run.summary_json["coding_execution_contract"]["control_ids"]
    assert pipeline_run.recovery_state_json["workspace_ids"] == [workspace.id]
    assert pipeline_run.recovery_state_json["agent_session_id"] == result["session"]["id"]
    stages = (
        await db.execute(
            select(WorkCodingPipelineStage)
            .where(WorkCodingPipelineStage.run_id == pipeline_run.id)
            .order_by(WorkCodingPipelineStage.stage_order.asc())
        )
    ).scalars().all()
    assert stages[0].status == "completed"
    assert stages[1].status == "running"
    assert pipeline_run.current_stage_key == stages[1].stage_key


async def test_start_work_item_coding_agent_execution_starts_governed_session(db, monkeypatch):
    actor = await _actor(db)
    item = await _work_item(db)
    plan, unit = await _approved_plan_and_unit(db, actor, item)
    captured: dict[str, str] = {}
    original_commit = db.commit
    commit_count = 0

    async def tracked_commit():
        nonlocal commit_count
        commit_count += 1
        await original_commit()

    monkeypatch.setattr(db, "commit", tracked_commit)

    async def fake_start_chat_turn(**kwargs):
        assert commit_count == 1
        captured["prompt"] = kwargs["prompt"]
        captured["agent_type"] = kwargs["agent_type"]
        captured["session_metadata_patch"] = kwargs["session_metadata_patch"]
        captured["platform_workflow_service"] = kwargs["platform_workflow_service"]
        session = Session(
            user_id=kwargs["user"].id,
            project_id=kwargs["project_id"] or None,
            agent_type=kwargs["agent_type"],
            status="running",
            metadata_={},
        )
        kwargs["db"].add(session)
        await kwargs["db"].flush()
        return session

    result = await start_work_item_coding_agent_execution(
        db,
        work_item_id=item.id,
        current_user=actor,
        payload={"change_plan_id": plan.id, "change_unit_ids": [unit.id]},
        start_chat_turn_func=fake_start_chat_turn,
    )

    assert result["status"] == "started"
    assert result["session"]["id"]
    assert result["work_url"] == f"/chat?area=work&work_item_id={item.id}"
    assert result["coding_url"] == f"/chat?area=coding&work_item_id={item.id}"
    _assert_governed_prompt(captured)
    await db.refresh(item)
    assert item.work_state == "in_progress"
    await _assert_start_audit_rows(db, item, plan, result)
    await _assert_prepared_workspace_and_pipeline(db, item, plan, unit, result)


async def test_start_work_item_coding_agent_execution_caps_model_visible_context(db):
    actor = await _actor(db)
    item = await _work_item(db, source_key="ACME-618")
    item.description = "description-fragment " * 500
    plan, unit = await _approved_plan_and_unit(db, actor, item)
    plan.understood_request = "understood-request-fragment " * 500
    plan.rollback_plan = "rollback-fragment " * 300
    captured: dict[str, str] = {}

    async def fake_start_chat_turn(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        session = Session(
            user_id=kwargs["user"].id,
            project_id=kwargs["project_id"] or None,
            agent_type=kwargs["agent_type"],
            status="running",
            metadata_={},
        )
        kwargs["db"].add(session)
        await kwargs["db"].flush()
        return session

    result = await start_work_item_coding_agent_execution(
        db,
        work_item_id=item.id,
        current_user=actor,
        payload={
            "change_plan_id": plan.id,
            "change_unit_ids": [unit.id],
            "operator_note": "operator-note-fragment " * 200,
        },
        start_chat_turn_func=fake_start_chat_turn,
    )

    assert "[... truncated by coding context budget ...]" in captured["prompt"]
    assert captured["prompt"].count("description-fragment") < 180
    assert captured["prompt"].count("understood-request-fragment") < 120
    assert captured["prompt"].count("rollback-fragment") < 80
    budget = result["pipeline_run"]["summary"]["context_budget"]
    assert budget["version"] == "coding_context_budget.v1"
    assert budget["fragments"]["description"]["truncated"] is True
    assert budget["fragments"]["understood_request"]["truncated"] is True
    assert budget["fragments"]["operator_request"]["truncated"] is True
    assert "content" not in budget["fragments"]["description"]


def test_coding_runtime_control_inventory_is_explicit_and_auditable():
    controls = coding_runtime_control_inventory()

    assert {control["id"] for control in controls} >= {
        "state_machine_completion_contract",
        "progress_quality_completion_evidence",
        "duplicate_read_only_reuse",
        "workspace_mutation_policy",
        "validation_outcome_contract",
    }
    for control in controls:
        assert control["owner"]
        assert control["purpose"]
        assert control["config_surface"]
        assert control["audit_event"]


async def test_start_work_item_coding_agent_execution_blocks_stale_plan_without_agent(db):
    actor = await _actor(db)
    item = await _work_item(db, source_key="ACME-616")
    plan, unit = await _approved_plan_and_unit(db, actor, item)
    item.last_source_updated_at = plan.approved_at + timedelta(minutes=3)
    called = False

    async def fake_start_chat_turn(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("agent must not start for stale source evidence")

    result = await start_work_item_coding_agent_execution(
        db,
        work_item_id=item.id,
        current_user=actor,
        payload={"change_plan_id": plan.id, "change_unit_ids": [unit.id]},
        start_chat_turn_func=fake_start_chat_turn,
    )

    assert result["status"] == "blocked"
    assert result["session"] is None
    assert result["work_url"] == f"/chat?area=work&work_item_id={item.id}"
    assert result["coding_url"] == f"/chat?area=coding&work_item_id={item.id}"
    assert result["next_actions"][0]["key"] == "open_work_item"
    assert result["blockers"][0]["code"] == "source_changed_after_plan"
    assert called is False
    await db.refresh(item)
    assert item.work_state == "needs_replan"
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == "secure_work.coding_agent_execution_blocked",
                AuditLog.resource_id == item.id,
            )
        )
    ).scalar_one()
    assert audit.details["blockers"][0]["code"] == "source_changed_after_plan"
