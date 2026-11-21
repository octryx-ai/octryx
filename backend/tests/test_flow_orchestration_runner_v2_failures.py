"""V2 flows that stop on failed validation or failed tools, with or without a repair policy."""

import pytest
from sqlalchemy import select

from app.models.runtime.audit import AuditLog
from app.services.flow_orchestration.runner import execute_flow_version
from app.services.flow_trace import serialize_flow_run
from tests.flow_orchestration_runner_support import _make_v2_flow_version, _node_runs


@pytest.mark.asyncio
async def test_execute_v2_flow_failed_validation_stops_without_repair_policy(db, monkeypatch):
    async def fake_execute_tool(tool_name, params, context):
        return {"validation": {"passed": False, "status": "failed", "summary": "pytest failed"}}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-validation-fail",
        "f-v2-validation-fail",
        "v2-validation-fail",
        [
            {"id": "input", "type": "trigger"},
            {
                "id": "validate",
                "type": "tool_step",
                "config": {"tool": "run_cli_command", "arguments": {"cmd": "pytest"}},
            },
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "validate"},
            {"source_node_id": "validate", "target_node_id": "out"},
        ],
    )
    version.runtime_settings = {"validation_loop": {"enabled": True, "require_validation": True}}

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"request": "go"})
    trace = serialize_flow_run(run)

    assert run.status == "failed"
    assert "pytest failed" in (run.last_error or "")
    assert trace["validation_loop"]["status"] == "failed"
    assert trace["validation_loop"]["required_action"] == "stop"
    assert trace["failure"]["category"] == "validation_failed"
    assert trace["failure"]["required_action"] == "stop"
    assert trace["failure"]["retryable"] is False
    assert trace["failure"]["detail"]["node_id"] == "validate"
    assert trace["acceptance"]["state"] == "failed"
    assert trace["acceptance"]["review_required"] is True
    runs = await _node_runs(db, run.id)
    assert [item.node_id for item in runs] == ["input", "validate"]
    audit_actions = [
        row.action
        for row in (await db.execute(select(AuditLog).where(AuditLog.session_id == run.session_id))).scalars().all()
    ]
    assert "flow.validation_failed" in audit_actions


@pytest.mark.asyncio
async def test_execute_v2_flow_failed_validation_records_repair_required_when_configured(db, monkeypatch):
    async def fake_execute_tool(tool_name, params, context):
        return {"validation": {"passed": False, "status": "failed", "summary": "lint failed"}}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-validation-repair",
        "f-v2-validation-repair",
        "v2-validation-repair",
        [
            {"id": "input", "type": "trigger"},
            {
                "id": "validate",
                "type": "tool_step",
                "config": {"tool": "run_cli_command", "arguments": {"cmd": "npm run lint"}},
            },
            {"id": "repair", "type": "agent_step", "config": {"prompt": "repair lint failures"}},
        ],
        [
            {"source_node_id": "input", "target_node_id": "validate"},
            {"source_node_id": "validate", "target_node_id": "repair"},
        ],
    )
    version.runtime_settings = {
        "validation_loop": {
            "enabled": True,
            "require_validation": True,
            "max_repair_attempts": 1,
            "repair_node_ids": ["repair"],
        }
    }

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"request": "go"})
    trace = serialize_flow_run(run)

    assert run.status == "failed"
    assert trace["validation_loop"]["status"] == "repair_required"
    assert trace["validation_loop"]["required_action"] == "repair"
    assert trace["validation_loop"]["repair_node_ids"] == ["repair"]
    assert trace["failure"]["category"] == "validation_failed"
    assert trace["failure"]["required_action"] == "repair"
    assert trace["failure"]["retryable"] is True
    runs = await _node_runs(db, run.id)
    assert [item.node_id for item in runs] == ["input", "validate"]


@pytest.mark.asyncio
async def test_execute_v2_flow_failed_tool_persists_error_and_stops(db, monkeypatch):
    async def fake_execute_tool(tool_name, params, context):
        return {"error": "blocked by policy"}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-fail",
        "f-v2-fail",
        "v2-fail",
        [
            {"id": "input", "type": "trigger"},
            {"id": "tool", "type": "tool_step", "config": {"tool": "blocked_tool", "arguments": {}}},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "tool"},
            {"source_node_id": "tool", "target_node_id": "out"},
        ],
    )

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={})
    runs = await _node_runs(db, run.id)

    assert run.status == "failed"
    assert run.last_error == "Node tool failed: flow_node_failed error_type=ToolResultFailedError"
    trace = serialize_flow_run(run)
    # Policy wording in an untyped tool error does not make a policy refusal: only the typed
    # ``denied_by_policy`` category does (see the tool-deny test above).
    assert trace["failure"]["category"] == "tool_error"
    assert trace["failure"]["error_class_source"] == "explicit"
    assert trace["failure"]["detail"]["node_id"] == "tool"
    assert [(item.node_id, item.status) for item in runs] == [
        ("input", "completed"),
        ("tool", "failed"),
    ]
    assert runs[1].error == "flow_node_failed error_type=ToolResultFailedError"
    assert runs[1].trace_refs_json["tool"] == "blocked_tool"
    assert runs[1].trace_refs_json["error"] == "flow_node_failed error_type=ToolResultFailedError"
