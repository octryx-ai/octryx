"""The platform makes its own test evidence; the agent's output format never stops a run.

Live after-2: 26716dd1 (python-bug) paused evidence_unresolved because `python3 -m pytest -q` named none of its 11
tests; 8795ff62 (node-bug) paused phase_not_finished because `node --test` was no test run for the Stop at all. Every
stack's runner is data (stacks.json test_runner, a per-test report through report_env or summary_only); node's spec
output is read; the platform's own runs (pipeline, red_on_base) attribute each test from their own report; evidence
an agent's run cannot give is the pipeline's to judge when one follows; an unfinished pass goes on by itself."""

from __future__ import annotations

import copy

import pytest

from app.services.engineering_knowledge.stacks import all_report_env, built_in, report_env, test_runners
from app.services.workflow_checks.test_output import parse
from app.services.workflow_runs.octryx.system_tests import summary_counts
from app.services.workflow_runs.red_on_base import outcomes

PYTEST_Q = "...........                                                              [100%]\n11 passed in 0.08s\n"
NODE_SPEC = ("✔ a page past the end is empty (1.3ms)\n✔ booklist --colour red (69.7ms)\nℹ tests 2\nℹ suites 0\n"
             "ℹ pass 2\nℹ fail 0\nℹ cancelled 0\nℹ skipped 0\n")
NODE_JUNIT = ('<?xml version="1.0" encoding="utf-8"?>\n<testsuites>\n'
              '<testcase name="a page past the end is empty" time="0.001" classname="test" '
              'file="test/books.test.js"/>\n<testcase name="booklist --colour red" time="0.07" classname="test" '
              'file="test/cli.test.js"><failure message="expected red"/></testcase>\n</testsuites>\n')


def test_every_stack_with_tests_names_its_runner_and_how_the_platform_reads_each_test():
    for name, stack in built_in()["stacks"].items():
        runner = stack.get("test_runner")
        assert isinstance(runner, dict) and runner.get("commands"), f"{name}: no test_runner"
        assert runner.get("report_env") or runner.get("evidence_args") or runner.get("summary_only") is True, (
            f"{name}: no per-test report (report_env / evidence_args) and not marked summary_only")
    assert {"PYTEST_ADDOPTS", "NODE_OPTIONS"} <= set(all_report_env())
    assert report_env("npm test", "/r.xml")["NODE_OPTIONS"].endswith("--test-reporter-destination=/r.xml")


def test_node_runs_are_test_runs_and_their_spec_output_is_read():
    from app.services.workflow_runs.octryx.hooks import test_prefixes

    assert ("node", "--test") in test_prefixes(None) and ("npm", "test") in test_prefixes(None)
    parsed = parse(NODE_SPEC)
    assert (parsed.format, parsed.executed(), parsed.problems) == ("node", 2, [])
    assert summary_counts(NODE_SPEC) == {"passed": 2}  # a piped green run is green, not "no summary"
    assert summary_counts(NODE_SPEC.replace("ℹ fail 0", "ℹ fail 1"))["failed"] == 1
    assert any(runner.get("options") == "any" for runner in test_runners())


def test_the_base_run_attributes_each_node_test_from_the_platforms_own_report():
    asked = {"tests": ["test/books.test.js::a page past the end is empty", "test/cli.test.js::booklist --colour red",
                       "test/cli.test.js::not there"]}
    assert outcomes(asked, {"command": "node --test test/", "output_tail": NODE_SPEC, "junit_xml": NODE_JUNIT}) == {
        "test/books.test.js::a page past the end is empty": "passed",
        "test/cli.test.js::booklist --colour red": "failed", "test/cli.test.js::not there": "missing"}


def _with_pipeline_after_green(definition: dict) -> dict:
    definition = copy.deepcopy(definition)
    definition["nodes"].insert(-1, {"id": "pipe", "type": "platform_action", "config": {"action": "pipeline.run"}})
    for edge in definition["edges"]:
        if edge["source_node_id"] == "green" and edge.get("when") == "passed":
            edge["target_node_id"] = "pipe"
    definition["edges"].append({"id": "e10", "source_node_id": "pipe", "target_node_id": "fine", "when": "succeeded"})
    definition["edges"].append({"id": "e11", "source_node_id": "pipe", "target_node_id": "make", "when": "failed",
                                "kind": "loop", "max_iterations": 2})
    return definition


@pytest.mark.asyncio
async def test_a_quiet_pytest_run_does_not_pause_green_when_the_pipeline_judges_after_it(db, monkeypatch):
    """26716dd1 as a fixture: the bound test, `pytest -q` (11 passed, no names), the green gate, a pipeline after it."""
    from app.services.workflow_runs.gate_evaluation import _evaluate_gate
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.phase_outputs import submit_output
    from app.services.workflow_runs.test_runs import record_turn_test_runs
    from tests.test_merged_phase_reaches_green import (
        MERGE,
        _device_run,
        _launcher_reports_the_file,
        _with_green_gate,
    )
    from tests.test_workflow_run_hitl import _start

    _device_run(monkeypatch)
    _admin, run, _session = await _start(db, _with_pipeline_after_green(_with_green_gate(MERGE)))
    test = "e2e/python/tests/test_split.py::test_shares_add_up_to_the_total"
    await submit_output(db, run, "submit_reproduction", {"tests": [test], "symptom": "9.99 != 10.0"})
    _launcher_reports_the_file(run)
    parsed = parse(PYTEST_Q)
    assert parsed.problems  # the run names none of its 11 tests: unattributable
    await record_turn_test_runs(db, run, [{"source": "octryx", "all_green": True, **parsed.fields()}],
                                node_id="make")
    await _evaluate_gate(db, run, (await graph_for_run(db, run)).nodes["green"])
    assert run.status == "running" and run.pause_reason is None
    assert run.gate_results["green"]["state"] == "passed"


@pytest.mark.asyncio
async def test_an_unfinished_pass_goes_on_by_itself_until_it_ends_unfinished_stall_after_times(db, monkeypatch):
    """8795ff62: the turn ended unfinished; the same pass goes on with its delta instead of a pause for a person."""
    from app.services.workflow_runs.octryx import same_pass
    from app.services.workflow_runs.records import start_run
    from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
    from tests.test_workflow_size_class_merge import _definition

    continued = []

    async def go_on(_db, run, node_id, *, actor_id):
        continued.append(node_id)

    monkeypatch.setattr(same_pass, "continue_pass", go_on)
    workspace_id = await run_workspace(db, await admin_user(db))
    run = await start_run(db, user=await admin_user(db), workflow_key=await publish_phased(db, _definition({})),
                          project_id=workspace_id)
    assert await same_pass.continue_unfinished(db, run, "write") is True  # the first time: on it goes
    assert await same_pass.continue_unfinished(db, run, "write") is False  # stall_after (2): now a person decides
    assert continued == ["write"]


BASE_SPEC = ("✔ src/books.js (88.3ms)\n✔ a page past the end is empty (1.1ms)\n✖ page 1 is the first page (0.9ms)\n"
             "✔ a book line shows position, title and year (0.1ms)\nℹ tests 4\nℹ pass 3\nℹ fail 1\n")


def test_cfca8142_the_base_run_proves_the_node_reproduction_and_blames_nobody_for_a_gap():
    """cfca8142 as a fixture: the code file under e2e/ is no test, the red node test is attributed by its name, and a
    test the base run did not show is the platform's gap, never "passes on the base commit"."""
    from types import SimpleNamespace

    from app.services.workflow_runs.red_on_base import judge, record, request, unattributed

    test = "test/books.test.js::page 1 is the first page"
    run = SimpleNamespace(context={
        "base_sha": "d14b15e", "confirmed_tests": [test],
        "size_class": {"class": "S", "classes": {"S": {"red_on_base": True}}},
        "device_change": {"patch": "diff --git a/e2e/node/src/books.js b/e2e/node/src/books.js\n+fix\n"
                                   "diff --git a/e2e/node/test/books.test.js b/e2e/node/test/books.test.js\n+test\n"}})
    asked = request(run, "e2e/node")
    assert asked["files"] == ["test/books.test.js"] and "changed" in asked and asked["changed"] == [
        "test/books.test.js"]
    assert asked["report_env"]["NODE_OPTIONS"]
    report = {"command": "node --test test/books.test.js", "exit_code": 1, "output_tail": BASE_SPEC}
    assert judge(asked, report) == [] and unattributed(asked, report) == []
    record(run, asked, report, node_id="pipeline", entry=3)
    assert run.context["red_on_base"]["state"] == "proven"
    unseen = {**report, "output_tail": BASE_SPEC.replace("✖ page 1 is the first page (0.9ms)\n", "")}
    assert judge(asked, unseen) == [] and unattributed(asked, unseen) == [test]
    record(run, asked, unseen, node_id="pipeline", entry=4)
    assert run.context["red_on_base"]["state"] == "unattributed"


def test_the_device_gets_the_report_env_with_the_pipeline_view():
    from types import SimpleNamespace

    from app.services.workflow_runs.pipeline import contract_view

    run = SimpleNamespace(current_node_id="pipeline", node_state={"entry": 3}, context={"pipeline": {
        "state": "pending", "node_id": "pipeline", "entry": 3, "commands": ["node --test test/"], "path": [],
        "report_env": all_report_env()}})
    assert contract_view(run)["report_env"]["NODE_OPTIONS"]
