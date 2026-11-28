"""A gate the platform could not judge pauses ``evidence_unresolved``."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import WorkflowRun
from app.services.workflow_runs.records import main_session_id
from app.services.workflow_runs.test_runs import confirm_tests, gate_fields, record_test_run
from app.time_utils import utc_now
from tests.device_job_session_parity_support import CONFIRMED, _b_at_tests_first, _call
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_acceptance_support import _phase_turn, systems  # noqa: F401 - the stubbed Jira and GitHub fixture
from tests.workspace_preparation_support import _device_at_tests_first, _stop

pytestmark = pytest.mark.usefixtures("scripted_pool")

TEST_ID = f"{CONFIRMED}::test_rounds_half_up"
# pytest run one directory above the repository root: every classname gains a prefix no file of the run spells.
ELSEWHERE = ('<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1">'
             '<testcase classname="pay.tests.test_totals" name="test_rounds_half_up">'
             '<failure message="assert 2 == 3">assert 2 == 3</failure></testcase></testsuite></testsuites>')


@pytest.mark.asyncio
async def test_an_unresolvable_device_report_pauses_the_red_gate_without_consuming_a_loop(
        client, auth_headers, db, systems):  # noqa: F811
    run_id, working_copy, gateway, policy, _headers = await _device_at_tests_first(client, auth_headers, db, systems)
    at = utc_now() + timedelta(seconds=5)
    command = "pytest -v tests/ --junitxml=test-reports/report.xml"
    answer = await _stop(db, gateway, policy, [
        _call(gateway, "Write", at=at, file_path=str(working_copy / CONFIRMED)),
        _call(gateway, "Bash", at=at + timedelta(seconds=1), ok=False, command=command,
              test_report={"format": "junit", "junit_xml": ELSEWHERE},
              excerpt="Exit code 1\n1 failed in 0.02s")])
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "evidence_unresolved", "red")
    assert (answer["state"], answer["reason"]) == ("not_applicable", "workflow_run_paused"), answer
    gate = run.gate_results["red"]
    assert gate["state"] == "failed" and gate["results"][0]["unresolved"] is True
    assert "pay.tests.test_totals.test_rounds_half_up" in gate["results"][0]["detail"]
    pause = run.node_state["pause"]
    assert "could not match the test evidence" in pause["message"] and "Nothing was counted" in pause["message"]
    assert run.context["evidence_unresolved"]["unresolved"][0]["raw"] == "pay.tests.test_totals.test_rounds_half_up"
    assert int(dict(run.loop_counters or {}).get("loop-red", {}).get("used") or 0) == 0
    assert not run.context.get("follow_up_issue")
    assert dict(run.context.get("device_continuation") or {}).get("state") != "pending"
    actions = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]["actions"]
    assert [item["label"] for item in actions if item["key"] == "continue"] == ["Re-check the test evidence"]

    rechecked = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                  json={"action": "continue"})
    assert rechecked.status_code == 200, rechecked.text
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ("running", "tests_first")
    assert int(dict(run.loop_counters or {}).get("loop-red", {}).get("used") or 0) == 0


@pytest.mark.asyncio
async def test_a_chat_turn_whose_report_cannot_be_keyed_pauses_too(client, auth_headers, db, systems):  # noqa: F811
    _project, run_id, _working_copy = await _b_at_tests_first(client, auth_headers, db, systems)
    run = await db.get(WorkflowRun, run_id)
    session_id = await main_session_id(db, run)
    write = {"tool_name": "write_workspace_file", "status": "success", "result": {}}
    tests = {"tool_name": "run_test_suite", "status": "success",
             "result": {"stdout": ELSEWHERE, "exit_code": 1, "all_green": False}}
    await _phase_turn(db, session_id, [write, tests])
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "evidence_unresolved"), run.gate_results.get("red")
    assert int(dict(run.loop_counters or {}).get("loop-red", {}).get("used") or 0) == 0


@pytest.mark.asyncio
async def test_a_wrong_or_missing_test_is_still_the_agents_and_loops(client, auth_headers, db, systems):  # noqa: F811
    _project, run_id, _working_copy = await _b_at_tests_first(client, auth_headers, db, systems)
    run = await db.get(WorkflowRun, run_id)
    write = {"tool_name": "write_workspace_file", "status": "success", "result": {}}
    other = {"tool_name": "run_test_suite", "status": "success",
             "result": {"stdout": "tests/test_zero.py::test_zero PASSED\n1 passed in 0.01s", "exit_code": 0,
                        "all_green": True}}
    await _phase_turn(db, await main_session_id(db, run), [write, other])
    await db.refresh(run)
    assert run.status == "running" and run.current_node_id == "tests_first"
    assert run.loop_counters["loop-red"]["used"] == 1
    assert "not seen" in run.gate_results["red"]["results"][0]["detail"]
    assert not run.gate_results["red"]["results"][0].get("unresolved")


@pytest.mark.asyncio
async def test_a_clarify_run_keyed_later_once_the_contract_names_its_file(db, systems):  # noqa: F811
    run = WorkflowRun(workflow_key="x", workflow_kind="phased", status="running", context={})
    junit = ('<testsuite><testcase classname="tests.test_totals" name="test_rounds_half_up">'
             '<failure message="assert 2 == 3"/></testcase><testcase classname="tests.test_zero" name="test_zero"/>'
             '</testsuite>')
    from app.services.workflow_checks.test_output import parse

    record_test_run(run, {"source": "octryx", "all_green": False, **parse(junit).fields()}, node_id="clarify")
    assert len(run.context["tests"]["runs"][0]["unresolved"]) == 2
    confirm_tests(run, [TEST_ID, "tests/test_zero.py::test_zero"],
                  roles={TEST_ID: "new", "tests/test_zero.py::test_zero": "regression"})
    [resolved] = gate_fields(run)["test_runs"]
    assert {key: value["outcome"] for key, value in resolved["results"].items()} == {
        TEST_ID: "failed", "tests/test_zero.py::test_zero": "passed"}
    assert run.context["tests"]["red_seen"] is True


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


@pytest.mark.asyncio
async def test_a_re_check_at_a_gate_without_a_phase_re_runs_the_phase_that_leads_into_it(monkeypatch):
    from types import SimpleNamespace

    from app.services.workflow_runs import evidence_pause
    from app.services.workflow_runs.graph import NODE_GATE, NODE_PHASE

    nodes = {"fix": SimpleNamespace(kind=NODE_PHASE, config={}), "green": SimpleNamespace(kind=NODE_GATE, config={}),
             "review": SimpleNamespace(kind=NODE_GATE, config={"phase": "fix"})}
    graph = SimpleNamespace(nodes=nodes, edges=[SimpleNamespace(source="fix", target="green")])

    async def fake_graph(_db, _run):
        return graph

    monkeypatch.setattr("app.services.workflow_runs.graph.graph_for_run", fake_graph)
    run = SimpleNamespace(context={})
    assert await evidence_pause._rerun_node(run, "green", None) == "fix"
    assert await evidence_pause._rerun_node(run, "review", None) == "fix"
    assert await evidence_pause._rerun_node(run, "fix", None) == "fix"


@pytest.mark.asyncio
async def test_a_concurrent_test_run_goes_back_into_the_phase_with_the_hint_twice_then_pauses(monkeypatch):
    from types import SimpleNamespace

    from app.services.workflow_runs import evidence_pause
    from app.services.workflow_runs.graph import NODE_GATE, NODE_PHASE

    graph = SimpleNamespace(nodes={"fix": SimpleNamespace(kind=NODE_PHASE, config={}),
                                   "green": SimpleNamespace(kind=NODE_GATE, config={})},
                            edges=[SimpleNamespace(source="fix", target="green")])
    restarted, paused, events = [], [], []

    async def fake_graph(_db, _run):
        return graph

    async def fake_restart(_db, _run, node_id, *, actor_id):
        restarted.append(node_id)

    async def fake_pause(_db, _run, **kwargs):
        paused.append(kwargs["reason"])

    monkeypatch.setattr("app.services.workflow_runs.graph.graph_for_run", fake_graph)
    monkeypatch.setattr("app.services.workflow_runs.engine.restart_at", fake_restart)
    monkeypatch.setattr("app.services.workflow_runs.limits.pause_run", fake_pause)
    monkeypatch.setattr("app.services.workflow_runs.records.record_event",
                        lambda _db, _run, kind, **kwargs: events.append((kind, kwargs["detail"]["count"])))
    problem = ("the test files ran concurrently, so only their failures are attributed (run one test file at a time, "
               "or flutter test -j 1, for every test's result)")
    run = SimpleNamespace(context={"test_runs": [{"problems": [problem]}]}, node_state={"entry": 3})
    monkeypatch.setattr(evidence_pause, "_last_run", lambda _run: {"problems": [problem]})
    check = SimpleNamespace(type="tests_green", description="green", detail="evidence unresolved: not seen: x",
                            unresolved=True)
    for _ in range(3):
        await evidence_pause.pause_unresolved(None, run, [check], node_id="green")
    assert restarted == ["fix", "fix"] and events == [("evidence_rerun", 1), ("evidence_rerun", 2)]
    assert paused == ["evidence_unresolved"]
    hint = evidence_pause.rerun_hint(run, "fix")
    assert "flutter test --reporter json" in hint and "tail" in hint
    other = SimpleNamespace(context={}, node_state={})
    monkeypatch.setattr(evidence_pause, "_last_run", lambda _run: {"problems": ["unreadable report"]})
    await evidence_pause.pause_unresolved(None, other, [check], node_id="green")
    assert restarted == ["fix", "fix"] and paused == ["evidence_unresolved", "evidence_unresolved"]
