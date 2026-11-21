"""V2 routers, structured edge conditions, parallel branch joins and topological ordering."""

import pytest

from app.models.agent.orchestrator_agent import ORCHESTRATOR_PATTERN_PARALLEL
from app.services.flow_orchestration.runner import execute_flow_version
from tests.flow_orchestration_runner_support import _make_v2_flow_version, _node_runs


@pytest.mark.asyncio
async def test_execute_v2_flow_router_skips_unselected_branch(db, monkeypatch):
    calls = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append(tool_name)
        return {"selected": tool_name}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-router",
        "f-v2-router",
        "v2-router",
        [
            {"id": "input", "type": "trigger"},
            {
                "id": "router",
                "type": "router",
                "config": {
                    "routes": [{"when": {"field": "kind", "operator": "equals", "value": "a"}, "route": "yes"}],
                    "default_route": "no",
                },
            },
            {"id": "yes", "type": "tool_step", "config": {"tool": "yes_tool", "arguments": {}}},
            {"id": "no", "type": "tool_step", "config": {"tool": "no_tool", "arguments": {}}},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "router", "source_field": "kind", "target_field": "kind"},
            {"source_node_id": "router", "target_node_id": "yes", "condition": "route:yes"},
            {"source_node_id": "router", "target_node_id": "no", "condition": "route:no"},
            {"source_node_id": "yes", "target_node_id": "out", "source_field": "result.selected", "target_field": "selected"},
            {"source_node_id": "no", "target_node_id": "out", "source_field": "result.selected", "target_field": "selected"},
        ],
    )

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"kind": "a"})
    runs = await _node_runs(db, run.id)
    statuses = {item.node_id: item.status for item in runs}

    assert run.status == "completed"
    assert calls == ["yes_tool"]
    assert statuses["yes"] == "completed"
    assert statuses["no"] == "skipped"
    assert run.merged_output_json["final"] == {"result": {"selected": "yes_tool"}}


@pytest.mark.asyncio
async def test_execute_v2_flow_router_supports_structured_edge_conditions(db, monkeypatch):
    calls = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append(tool_name)
        if tool_name == "lookup_tool":
            return {"total": 2, "results": [{"id": "person-1"}]}
        return {"selected": tool_name}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-router-structured-condition",
        "f-v2-router-structured-condition",
        "v2-router-structured-condition",
        [
            {"id": "input", "type": "trigger"},
            {"id": "lookup", "type": "tool_step", "config": {"tool": "lookup_tool", "arguments": {}}},
            {
                "id": "router",
                "type": "router",
                "config": {
                    "routes": [
                        {"route": "found", "when": {"field": "result.total", "operator": "gt", "value": 0}},
                    ],
                    "default_route": "missing",
                },
            },
            {"id": "found", "type": "tool_step", "config": {"tool": "found_tool", "arguments": {}}},
            {"id": "missing", "type": "tool_step", "config": {"tool": "missing_tool", "arguments": {}}},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "lookup"},
            {"source_node_id": "lookup", "target_node_id": "router"},
            {
                "source_node_id": "router",
                "target_node_id": "found",
                "condition": {"field": "route", "operator": "equals", "value": "found"},
            },
            {
                "source_node_id": "router",
                "target_node_id": "missing",
                "condition": {"field": "route", "operator": "equals", "value": "missing"},
            },
            {
                "source_node_id": "found",
                "target_node_id": "out",
                "source_field": "result.selected",
                "target_field": "selected",
            },
            {
                "source_node_id": "missing",
                "target_node_id": "out",
                "source_field": "result.selected",
                "target_field": "selected",
            },
        ],
    )

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester")
    runs = await _node_runs(db, run.id)
    statuses = {item.node_id: item.status for item in runs}

    assert run.status == "completed"
    assert calls == ["lookup_tool", "found_tool"]
    assert statuses["found"] == "completed"
    assert statuses["missing"] == "skipped"
    assert run.merged_output_json["final"] == {"result": {"selected": "found_tool"}}


@pytest.mark.asyncio
async def test_execute_v2_flow_parallel_branches_join(db, monkeypatch):
    async def fake_execute_tool(tool_name, params, context):
        return {"branch": tool_name}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-parallel",
        "f-v2-parallel",
        "v2-parallel",
        [
            {"id": "input", "type": "trigger"},
            {"id": "parallel", "type": "parallel"},
            {"id": "left", "type": "tool_step", "config": {"tool": "left_tool", "arguments": {}}},
            {"id": "right", "type": "tool_step", "config": {"tool": "right_tool", "arguments": {}}},
            {"id": "join", "type": "join"},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "parallel"},
            {"source_node_id": "parallel", "target_node_id": "left"},
            {"source_node_id": "parallel", "target_node_id": "right"},
            {"source_node_id": "left", "target_node_id": "join", "source_field": "result.branch", "target_field": "left"},
            {"source_node_id": "right", "target_node_id": "join", "source_field": "result.branch", "target_field": "right"},
            {"source_node_id": "join", "target_node_id": "out", "source_field": "joined", "target_field": "branches"},
        ],
    )

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={})
    runs = await _node_runs(db, run.id)

    assert run.pattern_type == ORCHESTRATOR_PATTERN_PARALLEL
    assert run.status == "completed"
    assert {item.node_id for item in runs} == {"input", "parallel", "left", "right", "join", "out"}
    assert run.merged_output_json["final"] == {
        "result": {"branches": {"left": "left_tool", "right": "right_tool"}}
    }
