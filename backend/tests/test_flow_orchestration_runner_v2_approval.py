"""V2 approval pauses, resuming after approval, and rejecting or cancelling paused flows."""

import pytest
from sqlalchemy import select

from app.models import Approval
from app.models.agent.orchestrator_agent import ORCHESTRATOR_STATUS_CANCELLED
from app.models.runtime.audit import AuditLog
from app.services.flow_orchestration.dag.approval_resume import resume_v2_flow_dag
from app.services.flow_orchestration.dag.cancellation import cancel_v2_flow_dag
from app.services.flow_orchestration.runner import execute_flow_version
from app.services.flow_trace import serialize_flow_run
from tests.flow_orchestration_runner_support import _make_v2_flow_version, _node_runs


@pytest.mark.asyncio
async def test_execute_v2_flow_approval_pauses_and_stops_downstream(db):
    version = _make_v2_flow_version(
        db,
        "v2-pause",
        "f-v2-pause",
        "v2-pause",
        [
            {"id": "input", "type": "trigger"},
            {"id": "approval", "type": "approval"},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "approval"},
            {"source_node_id": "approval", "target_node_id": "out"},
        ],
    )

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={})
    runs = await _node_runs(db, run.id)

    assert run.status == "paused"
    assert [(item.node_id, item.status) for item in runs] == [
        ("input", "completed"),
        ("approval", "paused"),
    ]
    assert runs[1].trace_refs_json["requires_human_review"] is True
    assert runs[1].trace_refs_json["pause_reason"] == "Approval node paused the flow."
    approvals = (await db.execute(select(Approval))).scalars().all()
    assert len(approvals) == 1
    assert approvals[0].status == "pending"
    assert runs[1].output_json["approval_id"] == approvals[0].id
    decision_trace = runs[1].trace_refs_json["decision_trace"]
    assert decision_trace["source"]["kind"] == "human_review"
    assert decision_trace["source"]["approval_id"] == approvals[0].id
    assert decision_trace["next_action"]["action"] == "wait_for_review"
    trace_run = serialize_flow_run(run)
    assert trace_run["failure"]["category"] == "human_review_required"
    assert trace_run["failure"]["required_action"] == "human_review"
    assert trace_run["acceptance"]["state"] == "needs_review"
    assert trace_run["acceptance"]["required_action"] == "human_review"
    assert trace_run["plan"]["status"] == "blocked"
    approval_step = trace_run["plan"]["steps"][1]
    assert approval_step["status"] == "blocked"
    assert approval_step["required_action"] == "human_review"
    assert "Approval node paused the flow." in approval_step["reason"]
    audit_actions = {row.action for row in (await db.execute(select(AuditLog))).scalars().all()}
    assert "flow.approval_paused" in audit_actions


@pytest.mark.asyncio
async def test_resume_v2_flow_after_approval_continues_downstream_without_rerunning_upstream(db, monkeypatch):
    calls = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append((tool_name, params))
        return {"continued": True, "params": params}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-resume",
        "f-v2-resume",
        "v2-resume",
        [
            {"id": "input", "type": "trigger"},
            {"id": "approval", "type": "approval", "config": {"title": "Approve continuation"}},
            {"id": "tool", "type": "tool_step", "config": {"tool": "resume_tool"}},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "approval"},
            {"source_node_id": "approval", "target_node_id": "tool"},
            {"source_node_id": "tool", "target_node_id": "out", "source_field": "result.continued", "target_field": "continued"},
        ],
    )

    paused_run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"request": "go"})
    paused_node_runs = await _node_runs(db, paused_run.id)
    approval_id = paused_node_runs[1].output_json["approval_id"]

    resumed = await resume_v2_flow_dag(
        db,
        run_id=paused_run.id,
        decision="approve",
        approval_id=approval_id,
        human_input={"operator_note": "ok"},
        user_id="reviewer",
    )
    runs = await _node_runs(db, resumed.id)
    approval = await db.get(Approval, approval_id)

    assert resumed.status == "completed"
    assert approval.status == "approved"
    assert [(item.node_id, item.status) for item in runs] == [
        ("input", "completed"),
        ("approval", "completed"),
        ("tool", "completed"),
        ("out", "completed"),
    ]
    assert calls == [("resume_tool", runs[1].output_json)]
    assert runs[1].output_json["human_input"] == {"operator_note": "ok"}
    assert resumed.merged_output_json["final"] == {"result": {"continued": True}}
    trace_run = serialize_flow_run(resumed)
    assert trace_run["acceptance"]["state"] == "completed"
    assert trace_run["acceptance"]["accepted"] is True
    audit_actions = {row.action for row in (await db.execute(select(AuditLog))).scalars().all()}
    assert {
        "flow.acceptance_state_changed",
        "flow.approval_paused",
        "flow.approval_approved",
        "flow.resumed_completed",
    } <= audit_actions


@pytest.mark.asyncio
async def test_reject_v2_flow_cancels_paused_and_downstream_nodes(db):
    version = _make_v2_flow_version(
        db,
        "v2-reject",
        "f-v2-reject",
        "v2-reject",
        [
            {"id": "input", "type": "trigger"},
            {"id": "approval", "type": "approval"},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "approval"},
            {"source_node_id": "approval", "target_node_id": "out"},
        ],
    )
    paused_run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={})
    approval_id = (await _node_runs(db, paused_run.id))[1].output_json["approval_id"]

    rejected = await resume_v2_flow_dag(
        db,
        run_id=paused_run.id,
        decision="reject",
        approval_id=approval_id,
        human_input={},
        user_id="reviewer",
        reason="Not acceptable",
    )
    runs = await _node_runs(db, rejected.id)
    approval = await db.get(Approval, approval_id)

    assert rejected.status == ORCHESTRATOR_STATUS_CANCELLED
    assert approval.status == "rejected"
    assert [(item.node_id, item.status) for item in runs] == [
        ("input", "completed"),
        ("approval", "cancelled"),
        ("out", "cancelled"),
    ]
    assert "Not acceptable" in rejected.last_error
    trace_run = serialize_flow_run(rejected)
    assert trace_run["acceptance"]["state"] == "rejected"
    assert trace_run["acceptance"]["review_required"] is True


@pytest.mark.asyncio
async def test_cancel_v2_flow_cancels_pending_approval_and_downstream_nodes(db):
    version = _make_v2_flow_version(
        db,
        "v2-cancel",
        "f-v2-cancel",
        "v2-cancel",
        [
            {"id": "input", "type": "trigger"},
            {"id": "approval", "type": "approval"},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "approval"},
            {"source_node_id": "approval", "target_node_id": "out"},
        ],
    )
    paused_run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={})
    approval_id = (await _node_runs(db, paused_run.id))[1].output_json["approval_id"]

    cancelled = await cancel_v2_flow_dag(db, run_id=paused_run.id, user_id="reviewer", reason="Stop this run")
    runs = await _node_runs(db, cancelled.id)
    approval = await db.get(Approval, approval_id)

    assert cancelled.status == ORCHESTRATOR_STATUS_CANCELLED
    assert approval.status == "rejected"
    assert [(item.node_id, item.status) for item in runs] == [
        ("input", "completed"),
        ("approval", "cancelled"),
        ("out", "cancelled"),
    ]
