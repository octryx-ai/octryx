"""A saved malformed rule or predicate fails the router node before it picks a branch on full, partial, approval-resumed and interrupted runs, while valid saved rules keep their behaviour."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.runtime.flow_definition import FlowNodeRun
from app.services.flow_orchestration.dag.approval_resume import resume_v2_flow_dag
from app.services.flow_orchestration.dag.execute import execute_v2_partial_flow_dag
from app.services.flow_orchestration.dag.interrupted import resume_interrupted_v2_flow_dag
from app.services.flow_orchestration.runner import execute_flow_version
from app.services.flow_trace import serialize_flow_run
from tests.flow_conditional_rules_support import _router_flow
from tests.flow_orchestration_runner_support import _make_v2_flow_version, _node_runs

# --- real runs of saved snapshots -----------------------------------------------------


def _record_tools(monkeypatch) -> list[str]:
    calls: list[str] = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append(tool_name)
        return {"selected": tool_name}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    return calls


def _save(db, key: str, definition: dict):
    """A snapshot written directly, not through the validating API, to exercise runtime validation."""
    return _make_v2_flow_version(db, key, f"f-{key}", key, definition["nodes"], definition["edges"])


def _assert_failed_before_branching(run, runs, calls, code: str) -> None:
    statuses = {item.node_id: item.status for item in runs}
    assert run.status == "failed"
    assert run.last_error.startswith("Node router failed")
    assert run.last_error.endswith(f": {code} error_type=RouterRuleInvalidError")
    assert statuses["router"] == "failed"
    assert calls == [], "no branch step runs"
    assert not {"a", "b", "out"} & {item.node_id for item in runs if item.status != "skipped"}
    trace = serialize_flow_run(run)
    assert (trace["failure"]["category"], trace["failure"]["required_action"]) == (
        "input_contract_error",
        "fix_workflow_configuration",
    )
    assert trace["acceptance"]["state"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "when",
    [
        {"field": "kind", "operator": "matches", "value": "a"},
        {"field": "", "operator": "equals", "value": "a"},
        {"field": "kind", "operator": "in", "value": "a"},
        "kind == a",
        # falsy non-object conditions never match like "always" (which would run the first branch)
        False,
        0,
        "",
        [],
        # non-finite or boolean thresholds
        {"field": "amount", "operator": "gt", "value": "nan"},
        {"field": "amount", "operator": "lt", "value": "Infinity"},
        {"field": "amount", "operator": "gte", "value": True},
        # the key form names no operator
        {"field": "kind", "equals": "a"},
    ],
)
async def test_a_saved_malformed_rule_fails_the_run_instead_of_choosing_the_default(db, monkeypatch, when):
    calls = _record_tools(monkeypatch)
    version = _save(db, f"cr-bad-{abs(hash(str(when)))}", _router_flow([{"route": "a", "when": when}]))

    run = await execute_flow_version(
        db, flow_version_id=version.id, user_id="tester", initial_input={"kind": "a", "amount": 7}
    )

    _assert_failed_before_branching(run, await _node_runs(db, run.id), calls, "router_rule_invalid")


@pytest.mark.asyncio
async def test_a_saved_malformed_connection_predicate_fails_before_any_branch(db, monkeypatch):
    calls = _record_tools(monkeypatch)
    definition = _router_flow(
        [{"route": "a", "when": {"field": "kind", "operator": "equals", "value": "a"}}],
        connections=[("a", {"field": "route", "operator": "like", "value": "a"}), ("b", "route:b")],
    )
    version = _save(db, "cr-bad-predicate", definition)

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"kind": "a"})

    _assert_failed_before_branching(run, await _node_runs(db, run.id), calls, "router_condition_invalid")


@pytest.mark.asyncio
async def test_a_partial_run_from_a_malformed_router_fails_the_same_way(db, monkeypatch):
    calls = _record_tools(monkeypatch)
    version = _save(db, "cr-bad-partial", _router_flow([{"route": "a", "when": {"field": "kind", "operator": "gt", "value": "x"}}]))
    await db.flush()

    run = await execute_v2_partial_flow_dag(
        db, version=version, start_node_id="router", parent_session_id=None, project_id=None,
        initial_input={"kind": "a"}, user_id="tester", agent_type="diagnosis",
    )

    _assert_failed_before_branching(run, await _node_runs(db, run.id), calls, "router_rule_invalid")


@pytest.mark.asyncio
async def test_a_run_resumed_after_approval_fails_on_a_malformed_rule(db, monkeypatch):
    calls = _record_tools(monkeypatch)
    definition = _router_flow([{"route": "a", "when": {"field": "kind", "operator": "exists", "value": "yes"}}])
    definition["nodes"].insert(1, {"id": "approval", "type": "approval", "config": {"title": "Go"}})
    definition["edges"][0] = {"source_node_id": "input", "target_node_id": "approval"}
    definition["edges"].insert(1, {"source_node_id": "approval", "target_node_id": "router"})
    version = _save(db, "cr-bad-resume", definition)
    paused = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"kind": "a"})
    approval_id = next(r for r in await _node_runs(db, paused.id) if r.node_id == "approval").output_json["approval_id"]

    resumed = await resume_v2_flow_dag(
        db, run_id=paused.id, decision="approve", approval_id=approval_id, human_input={}, user_id="reviewer",
    )

    _assert_failed_before_branching(resumed, await _node_runs(db, resumed.id), calls, "router_rule_invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rules", "initial_input", "expected"),
    [
        # first match wins even when a later rule matches too
        ([{"route": "a", "when": {"field": "kind", "operator": "==", "value": "x"}},
          {"route": "b", "when": {"field": "kind", "operator": "equals", "value": "x"}}], {"kind": "x"}, ["a_tool"]),
        # nothing matches: the default
        ([{"route": "a", "when": {"field": "kind", "operator": "in", "value": ["p", "q"]}}], {"kind": "x"}, ["b_tool"]),
        # numeric string threshold keeps working
        ([{"route": "a", "when": {"field": "amount", "operator": "gt", "value": "5"}}], {"amount": 7}, ["a_tool"]),
        # structured operand: a list of objects contains a matching object (existing membership semantics)
        ([{"route": "a", "when": {"field": "tags", "operator": "contains", "value": {"k": "v"}}}],
         {"tags": [{"k": "x"}, {"k": "v"}]}, ["a_tool"]),
        ([{"route": "a", "when": {"field": "tags", "operator": "not_contains", "value": ["p", 1]}}], {"tags": [["p", 1]]}, ["b_tool"]),
        # an explicitly unconditional rule always matches
        ([{"route": "b", "when": {}}, {"route": "a", "when": {"field": "kind", "operator": "equals", "value": "x"}}], {"kind": "x"},
         ["b_tool"]),
    ],
)
async def test_valid_saved_rules_keep_their_behaviour(db, monkeypatch, rules, initial_input, expected):
    calls = _record_tools(monkeypatch)
    version = _save(db, f"cr-ok-{abs(hash(str(rules)))}", _router_flow(rules))

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input=initial_input)

    assert run.status == "completed", run.last_error
    assert calls == expected


@pytest.mark.asyncio
async def test_a_valid_custom_predicate_and_the_explicit_fallback_keep_working(db, monkeypatch):
    calls = _record_tools(monkeypatch)
    definition = _router_flow(
        [{"route": "a", "when": {"field": "kind", "operator": "equals", "value": "a"}}],
        connections=[("a", {"field": "route", "operator": "equals", "value": "a"}), ("b", None)],
    )
    version = _save(db, "cr-ok-predicate", definition)

    matched = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"kind": "a"})
    fallback = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"kind": "z"})

    assert (matched.status, fallback.status) == ("completed", "completed")
    assert calls == ["a_tool", "b_tool"]


@pytest.mark.asyncio
async def test_an_interrupted_run_resumed_at_a_malformed_router_fails_before_branching(db, monkeypatch):
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
        return {"kind": "a"}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    definition = _router_flow([{"route": "a", "when": {"field": "kind", "operator": "is", "value": "a"}}])
    definition["nodes"].insert(1, {"id": "first", "type": "tool_step", "config": {"tool": "first_tool", "arguments": {}}})
    definition["edges"][0] = {"source_node_id": "input", "target_node_id": "first"}
    definition["edges"].insert(1, {"source_node_id": "first", "target_node_id": "router"})
    version = _save(db, "cr-bad-interrupted", definition)
    with pytest.raises(SimulatedCrash):
        await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={})
    run_id = (await db.execute(select(FlowNodeRun.orchestrator_run_id).limit(1))).scalar_one()

    resumed = await resume_interrupted_v2_flow_dag(db, run_id=run_id, user_id="tester", reason="restart test")

    assert calls == ["first_tool", "first_tool"], "only the interrupted upstream step is retried"
    calls.clear()
    _assert_failed_before_branching(resumed, await _node_runs(db, resumed.id), calls, "router_rule_invalid")
