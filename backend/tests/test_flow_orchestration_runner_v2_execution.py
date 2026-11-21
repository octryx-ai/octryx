"""V2 flow execution persisting node runs and recording validation loop passes and acceptance warnings."""

import pytest

from app.services.flow_orchestration.runner import execute_flow_version
from app.services.flow_trace import serialize_flow_node_run, serialize_flow_run
from tests.flow_orchestration_runner_support import _make_v2_flow_version, _node_runs


@pytest.mark.asyncio
async def test_execute_v2_flow_tool_to_output_persists_node_runs(db, monkeypatch):
    calls = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append((tool_name, params, context.project_ids))
        return {
            "value": params["value"],
            "source": "fake",
            "total_matches": 10,
            "query": "token=super-secret",
            "results": [
                {
                    "id": f"r{index}",
                    "title": f"Evidence row {index}",
                    "source": "fixture",
                    "api_key": "super-secret",
                }
                for index in range(10)
            ],
            "_artifact_storage": "external_json_gzip",
            "artifact_id": "artifact-123",
            "payload_size_bytes": 2048,
            "usage": {"tokens_in": 3, "tokens_out": 5},
            "cost_estimate": {"usd": 0.001},
        }

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-tool",
        "f-v2-tool",
        "v2-tool",
        [
            {"id": "input", "type": "trigger"},
            {"id": "tool", "type": "tool_step", "config": {"tool": "fake_tool", "arguments": {"value": 7}}},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "tool"},
            {"source_node_id": "tool", "target_node_id": "out", "source_field": "result.value", "target_field": "value"},
        ],
    )

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"request": "go"})
    runs = await _node_runs(db, run.id)

    assert run.status == "completed"
    assert run.merged_output_json["final"] == {"result": {"value": 7}}
    assert calls == [("fake_tool", {"value": 7}, [])]
    assert [(item.node_id, item.status) for item in runs] == [
        ("input", "completed"),
        ("tool", "completed"),
        ("out", "completed"),
    ]
    assert runs[1].input_json == {"request": "go"}
    assert runs[1].output_json["result"]["value"] == 7
    assert runs[1].evidence_summary_json["count"] == 10
    assert runs[1].evidence_summary_json["examples"][0]["title"] == "Evidence row 0"
    assert runs[1].artifact_refs_json[0]["artifact_id"] == "artifact-123"
    assert runs[1].trace_refs_json["tool"] == "fake_tool"
    decision_trace = runs[1].trace_refs_json["decision_trace"]
    assert decision_trace["kind"] == "flow_v2_node_decision"
    assert decision_trace["source"] == {"kind": "tool_call", "tool": "fake_tool"}
    assert decision_trace["next_action"] == {"action": "continue_downstream"}
    assert decision_trace["basis"]["evidence_summary"]["query"] == "[redacted]"
    assert len(decision_trace["basis"]["evidence_refs"]) == 5
    assert "super-secret" not in str(decision_trace)
    assert runs[1].token_usage_json == {"tokens_in": 3, "tokens_out": 5}
    assert runs[1].cost_estimate_json == {"usd": 0.001}
    trace_node = serialize_flow_node_run(runs[1])
    assert trace_node["decision_trace"]["basis"]["evidence_refs"][0]["title"] == "Evidence row 0"
    trace_run = serialize_flow_run(run)
    assert trace_run["progress"]["phase"] == "completed"
    assert trace_run["runtime_lease"]["last_heartbeat_at"]
    assert trace_run["runtime_lease"]["is_stale"] is False
    assert trace_run["plan"]["status"] == "completed"
    assert [(step["node_id"], step["status"]) for step in trace_run["plan"]["steps"]] == [
        ("input", "done"),
        ("tool", "done"),
        ("out", "done"),
    ]
    assert trace_run["plan"]["steps"][1]["links"]["flow_node_run_id"] == runs[1].id
    assert trace_run["acceptance"]["state"] == "completed"
    assert trace_run["acceptance"]["accepted"] is True


@pytest.mark.asyncio
async def test_execute_v2_flow_records_validation_loop_pass(db, monkeypatch):
    async def fake_execute_tool(tool_name, params, context):
        return {"validation": {"passed": True, "status": "passed", "summary": "pytest passed"}}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-validation-pass",
        "f-v2-validation-pass",
        "v2-validation-pass",
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

    assert run.status == "completed"
    assert trace["validation_loop"]["status"] == "passed"
    assert trace["validation_loop"]["passed_check_count"] == 1
    assert trace["validation_loop"]["checks"][0]["node_id"] == "validate"
    assert trace["acceptance"]["state"] == "validated"
    assert trace["acceptance"]["accepted"] is True


@pytest.mark.asyncio
async def test_execute_v2_flow_records_acceptance_warnings(db, monkeypatch):
    async def fake_execute_tool(tool_name, params, context):
        return {"validation": {"status": "warning", "summary": "coverage below target"}}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-validation-warning",
        "f-v2-validation-warning",
        "v2-validation-warning",
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

    assert run.status == "completed"
    assert trace["validation_loop"]["status"] == "warnings"
    assert trace["validation_loop"]["warning_check_count"] == 1
    assert trace["acceptance"]["state"] == "warnings"
    assert trace["acceptance"]["required_action"] == "review_warnings"
