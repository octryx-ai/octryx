"""A router branch without a connection fails visibly instead of running the first connection.

Selected branches and the explicit unconditional fallback keep their behaviour. An unmatched
branch with no fallback fails the router node with ``router_branch_unmatched``, persists the
failed node and run, and runs nothing downstream. This holds in full, partial, approval-resume and
interrupted-resume runs. The validator refuses only branches it can prove are unconnected.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.runtime.flow_definition import FlowNodeRun
from app.services.flow_orchestration.dag.approval_resume import resume_v2_flow_dag
from app.services.flow_orchestration.dag.execute import execute_v2_partial_flow_dag
from app.services.flow_orchestration.dag.interrupted import resume_interrupted_v2_flow_dag
from app.services.flow_orchestration.router_branches import (
    RouterBranchUnmatchedError,
    declared_router_branches,
    select_router_targets,
    unconnected_router_branches,
)
from app.services.flow_orchestration.runner import execute_flow_version
from app.services.flow_trace import serialize_flow_run
from app.services.flow_v2_validation import validate_flow_definition_v2
from tests.flow_orchestration_runner_support import _make_v2_flow_version, _node_runs

_ROUTER = {
    "id": "router",
    "type": "router",
    "config": {"routes": [{"when": {"field": "kind", "operator": "equals", "value": "a"}, "route": "a"}], "default_route": "b"},
}


def _edge(target: str, condition=None) -> dict:
    edge = {"source_node_id": "router", "target_node_id": target}
    if condition is not None:
        edge["condition"] = condition
    return edge


def _definition(router_edges: list[dict], *, before_router: list[dict] | None = None) -> tuple[list, list]:
    """trigger -> [upstream] -> router -> its connected branch steps -> output (no orphan nodes)."""
    upstream = before_router or []
    branch_ids = [edge["target_node_id"] for edge in router_edges]
    nodes = [
        {"id": "input", "type": "trigger"},
        *upstream,
        _ROUTER,
        *[{"id": name, "type": "tool_step", "config": {"tool": f"{name}_tool", "arguments": {}}} for name in branch_ids],
        {"id": "out", "type": "output"},
    ]
    chain = ["input", *[node["id"] for node in upstream], "router"]
    edges = [{"source_node_id": source, "target_node_id": target} for source, target in zip(chain, chain[1:], strict=False)]
    edges += router_edges
    edges += [{"source_node_id": name, "target_node_id": "out"} for name in branch_ids]
    return nodes, edges


def _record_tools(monkeypatch) -> list[str]:
    calls: list[str] = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append(tool_name)
        return {"selected": tool_name, "kind": "z"}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    return calls


def _assert_refused_without_downstream(run, runs: list[FlowNodeRun], calls: list[str], *, upstream_calls=()):
    statuses = {item.node_id: item.status for item in runs}
    assert run.status == "failed"
    assert run.completed_at is not None
    # Full and partial runs: "Node router failed: ..."; resumes add "after resume" / "after interrupted resume".
    assert run.last_error.startswith("Node router failed")
    assert run.last_error.endswith(": router_branch_unmatched error_type=RouterBranchUnmatchedError")
    assert statuses["router"] == "failed"
    assert list(calls) == list(upstream_calls), "no downstream agent or tool step may run"
    assert not {"a", "b", "fallback", "out"} & {item.node_id for item in runs if item.status != "skipped"}
    trace = serialize_flow_run(run)
    assert trace["failure"]["category"] == "input_contract_error"
    assert trace["failure"]["required_action"] == "fix_workflow_configuration"
    assert trace["acceptance"]["state"] == "failed"


# --- selection unit -----------------------------------------------------------------


def _matches_route(route: str):
    def matches(condition):
        if isinstance(condition, dict):
            return condition.get("route") == route
        return condition in {route, f"route:{route}"}

    return matches


def test_selection_runs_only_the_selected_branch_or_the_explicit_fallback():
    outgoing = [{"target": "A", "condition": "route:a"}, {"target": "B", "condition": "b"}, {"target": "F", "condition": ""}]
    assert select_router_targets(outgoing, _matches_route("a")) == {"A"}
    assert select_router_targets(outgoing, _matches_route("b")) == {"B"}
    assert select_router_targets(outgoing, _matches_route("other")) == {"F"}
    assert select_router_targets([], _matches_route("a")) == set(), "a router may end the flow"


def test_an_unmatched_branch_without_fallback_never_runs_the_first_connection():
    outgoing = [{"target": "A", "condition": "route:a"}, {"target": "B", "condition": {"route": "b"}}]
    with pytest.raises(RouterBranchUnmatchedError) as refused:
        select_router_targets(outgoing, _matches_route("other"))
    assert refused.value.code == "router_branch_unmatched"
    assert refused.value.category == "input_contract_error"


# --- static validation ----------------------------------------------------------------


def test_declared_branches_follow_rule_order_and_the_default():
    assert declared_router_branches(_ROUTER["config"]) == ["a", "b"]
    assert declared_router_branches({}) == ["default"]
    # A rule without a condition always matches: the default can never be picked.
    assert declared_router_branches({"routes": [{"route": "x"}, {"route": "y", "when": {"field": "k"}}]}) == ["x"]
    assert declared_router_branches({"routes": [{"target": "t", "when": {"field": "k", "operator": "equals", "value": 1}}]}) == [
        "t",
        "default",
    ]


@pytest.mark.parametrize(
    ("conditions", "unconnected"),
    [
        (["route:a", "route:b"], []),
        (["a", {"route": "b"}], []),
        (["route:a"], ["b"]),
        ([{"route": "a"}], ["b"]),
        (["route:a", None], []),  # explicit unconditional fallback
        (["route:a", ""], []),
        (["route:a", {"field": "route", "operator": "equals", "value": "b"}], []),  # custom predicate: not provable, kept
        ([], []),  # a router without connections ends the flow
    ],
)
def test_only_provably_unconnected_branches_are_reported(conditions, unconnected):
    assert unconnected_router_branches(_ROUTER["config"], conditions) == unconnected


def test_the_validator_refuses_a_provably_unconnected_branch_and_keeps_custom_predicates():
    nodes, edges = _definition([_edge("a", "route:a")])
    report = validate_flow_definition_v2({"schema_version": "2.0", "nodes": nodes, "edges": edges})
    assert report["valid"] is False
    unconnected = [error for error in report["errors"] if error["code"] == "router_branch_unconnected"]
    assert len(unconnected) == 1
    assert "branch b" in unconnected[0]["message"]

    for router_edges in (
        [_edge("a", "route:a"), _edge("b", "route:b")],
        [_edge("a", "route:a"), _edge("fallback")],
        [_edge("a", {"field": "route", "operator": "equals", "value": "a"}), _edge("b", {"field": "route", "operator": "equals", "value": "b"})],
    ):
        nodes, edges = _definition(router_edges)
        report = validate_flow_definition_v2({"schema_version": "2.0", "nodes": nodes, "edges": edges})
        assert "router_branch_unconnected" not in {error["code"] for error in report["errors"]}, router_edges


# --- real runs ------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "expected"), [("a", "a_tool"), ("z", "b_tool")])
async def test_a_full_run_executes_only_the_selected_branch(db, monkeypatch, kind, expected):
    calls = _record_tools(monkeypatch)
    nodes, edges = _definition([_edge("a", "route:a"), _edge("b", {"route": "b"})])
    version = _make_v2_flow_version(db, f"rb-sel-{kind}", f"f-rb-sel-{kind}", f"rb-sel-{kind}", nodes, edges)

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"kind": kind})

    assert run.status == "completed"
    assert calls == [expected]


@pytest.mark.asyncio
async def test_a_full_run_keeps_the_explicit_unconditional_fallback(db, monkeypatch):
    calls = _record_tools(monkeypatch)
    nodes, edges = _definition([_edge("a", "route:a"), _edge("fallback")])
    version = _make_v2_flow_version(db, "rb-fallback", "f-rb-fallback", "rb-fallback", nodes, edges)

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"kind": "z"})

    assert run.status == "completed"
    assert calls == ["fallback_tool"]


@pytest.mark.asyncio
async def test_a_full_run_fails_an_unconnected_branch_without_running_anything_downstream(db, monkeypatch):
    calls = _record_tools(monkeypatch)
    # A persisted definition with only branch "a" connected; the default "b" is not.
    nodes, edges = _definition([_edge("a", "route:a")])
    version = _make_v2_flow_version(db, "rb-unmatched", "f-rb-unmatched", "rb-unmatched", nodes, edges)

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"kind": "z"})

    _assert_refused_without_downstream(run, await _node_runs(db, run.id), calls)


@pytest.mark.asyncio
async def test_a_partial_run_from_the_router_fails_the_same_way(db, monkeypatch):
    calls = _record_tools(monkeypatch)
    nodes, edges = _definition([_edge("a", "route:a")])
    version = _make_v2_flow_version(db, "rb-partial", "f-rb-partial", "rb-partial", nodes, edges)
    await db.flush()

    run = await execute_v2_partial_flow_dag(
        db, version=version, start_node_id="router", parent_session_id=None, project_id=None,
        initial_input={"kind": "z"}, user_id="tester", agent_type="diagnosis",
    )

    _assert_refused_without_downstream(run, await _node_runs(db, run.id), calls)


@pytest.mark.asyncio
async def test_a_run_resumed_after_approval_fails_the_unconnected_branch(db, monkeypatch):
    calls = _record_tools(monkeypatch)
    nodes, edges = _definition(
        [_edge("a", "route:a")], before_router=[{"id": "approval", "type": "approval", "config": {"title": "Go"}}]
    )
    version = _make_v2_flow_version(db, "rb-approval", "f-rb-approval", "rb-approval", nodes, edges)
    paused = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"kind": "z"})
    approval_id = next(run for run in await _node_runs(db, paused.id) if run.node_id == "approval").output_json[
        "approval_id"
    ]

    resumed = await resume_v2_flow_dag(
        db, run_id=paused.id, decision="approve", approval_id=approval_id, human_input={}, user_id="reviewer",
    )

    _assert_refused_without_downstream(resumed, await _node_runs(db, resumed.id), calls)


@pytest.mark.asyncio
async def test_an_interrupted_run_resumed_at_the_router_fails_the_unconnected_branch(db, monkeypatch):
    class SimulatedCrash(BaseException):
        pass

    calls: list[str] = []
    crashed = False

    async def fake_execute_tool(tool_name, params, context):
        nonlocal crashed
        calls.append(tool_name)
        if tool_name == "first_tool" and not crashed:
            crashed = True
            raise SimulatedCrash("worker stopped before the router")
        return {"kind": "z"}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    nodes, edges = _definition(
        [_edge("a", "route:a")],
        before_router=[{"id": "first", "type": "tool_step", "config": {"tool": "first_tool", "arguments": {}}}],
    )
    version = _make_v2_flow_version(db, "rb-interrupted", "f-rb-interrupted", "rb-interrupted", nodes, edges)
    with pytest.raises(SimulatedCrash):
        await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={})
    run_id = (await db.execute(select(FlowNodeRun.orchestrator_run_id).limit(1))).scalar_one()

    resumed = await resume_interrupted_v2_flow_dag(db, run_id=run_id, user_id="tester", reason="restart test")

    _assert_refused_without_downstream(
        resumed, await _node_runs(db, resumed.id), calls, upstream_calls=["first_tool", "first_tool"]
    )
