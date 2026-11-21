"""V2 run auditing, tool call budgets and runtime project tool policy checks."""

import pytest
from sqlalchemy import select

from app.models import Project
from app.models.runtime.audit import AuditLog
from app.services.flow_orchestration.runner import execute_flow_version
from app.services.flow_trace import serialize_flow_run
from tests.flow_orchestration_runner_support import _make_v2_flow_version, _node_runs


@pytest.mark.asyncio
async def test_execute_v2_flow_audits_run_and_node_lifecycle(db):
    version = _make_v2_flow_version(
        db,
        "v2-audit",
        "f-v2-audit",
        "v2-audit",
        [
            {"id": "input", "type": "trigger"},
            {"id": "out", "type": "output"},
        ],
        [
            {
                "source_node_id": "input",
                "target_node_id": "out",
                "source_field": "request",
                "target_field": "result",
            }
        ],
    )

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"request": "go"})

    assert run.status == "completed"
    audit_actions = [row.action for row in (await db.execute(select(AuditLog))).scalars().all()]
    assert "flow.run_started" in audit_actions
    assert "flow.run_completed" in audit_actions
    assert audit_actions.count("flow.node_started") == 2
    assert audit_actions.count("flow.node_completed") == 2


@pytest.mark.asyncio
async def test_execute_v2_flow_stops_when_tool_call_budget_is_exceeded(db, monkeypatch):
    calls = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append((tool_name, params, context))
        return {"result": "should-not-run"}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-tool-budget",
        "f-v2-tool-budget",
        "v2-tool-budget",
        [
            {"id": "input", "type": "trigger"},
            {"id": "tool", "type": "tool_step", "config": {"tool": "budgeted_tool"}},
            {"id": "out", "type": "output"},
        ],
        [
            {
                "source_node_id": "input",
                "target_node_id": "tool",
                "source_field": "request",
                "target_field": "arguments",
            },
            {"source_node_id": "tool", "target_node_id": "out"},
        ],
    )
    version.runtime_settings = {"max_tool_calls": 0}

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"request": {}})
    runs = await _node_runs(db, run.id)

    assert run.status == "failed"
    assert "max_tool_calls=0" in run.last_error
    trace = serialize_flow_run(run)
    assert trace["failure"]["category"] == "budget_exceeded"
    assert trace["failure"]["required_action"] == "adjust_runtime_limits"
    assert trace["failure"]["detail"]["node_id"] == "tool"
    assert trace["acceptance"]["state"] == "failed"
    assert calls == []
    assert [(item.node_id, item.status) for item in runs] == [
        ("input", "completed"),
        ("tool", "failed"),
    ]
    audit_actions = {row.action for row in (await db.execute(select(AuditLog))).scalars().all()}
    assert {"flow.budget_exceeded", "flow.node_failed"} <= audit_actions


@pytest.mark.asyncio
async def test_execute_v2_flow_rechecks_project_tool_policy_at_runtime(db):
    project = Project(
        id="project-tool-deny",
        name="tool-deny",
        description="Runtime tool policy deny test",
        config={"tool_policy": {"deny_patterns": ["get_current_time"]}},
        is_active=True,
    )
    db.add(project)
    version = _make_v2_flow_version(
        db,
        "v2-runtime-policy",
        "f-v2-runtime-policy",
        "v2-runtime-policy",
        [
            {"id": "input", "type": "trigger"},
            {"id": "tool", "type": "tool_step", "config": {"tool": "get_current_time"}},
            {"id": "out", "type": "output"},
        ],
        [
            {
                "source_node_id": "input",
                "target_node_id": "tool",
                "source_field": "request",
                "target_field": "arguments",
            },
            {"source_node_id": "tool", "target_node_id": "out"},
        ],
    )

    run = await execute_flow_version(
        db,
        flow_version_id=version.id,
        project_id=project.id,
        user_id="tester",
        initial_input={"request": {}},
    )
    runs = await _node_runs(db, run.id)

    assert run.status == "failed"
    # The stored error carries fixed facts (the typed policy refusal), never the tool result's text.
    assert run.last_error == "Node tool failed: flow_node_failed error_type=ToolPolicyDeniedError"
    trace = serialize_flow_run(run)
    assert trace["failure"]["category"] == "policy_blocked"
    assert trace["failure"]["severity"] == "critical"
    assert trace["failure"]["required_action"] == "review_policy"
    assert runs[1].node_id == "tool"
    assert runs[1].status == "failed"
