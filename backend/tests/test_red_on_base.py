"""The confirmed tests run on the base commit in the pipeline and must fail there,
so a small item may write its test and its fix in one turn and a weakened test is still caught
(``workflow_runs/red_on_base``)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.engineering_knowledge.stacks import all_report_env, only_files_specs
from app.services.workflow_runs.red_on_base import judge, no_test_started, outcomes, record, request

TEST = "tests/test_grind.py::test_grind_starts_at_15"
OTHER = "tests/test_grind.py::test_stepper_stops_at_the_ends"
ASKED = {"base": "b" * 40, "tests": [TEST, OTHER], "files": ["tests/test_grind.py"]}


def _output(**outcomes: str) -> str:
    lines = [f"tests/test_grind.py::{name} {word}" for name, word in outcomes.items()]
    return "\n".join(["============ test session starts ============", *lines,
                      f"====== {len(lines)} failed in 0.1s ======"])


def test_every_confirmed_test_red_on_the_base_proves_the_reproduction():
    report = {"command": "pytest -v tests/test_grind.py", "exit_code": 1,
              "output_tail": _output(test_grind_starts_at_15="FAILED", test_stepper_stops_at_the_ends="FAILED")}
    assert judge(ASKED, report) == []


def test_a_confirmed_test_green_on_the_base_does_not_reproduce_and_a_missing_run_is_red_too():
    report = {"command": "pytest -v tests/test_grind.py", "exit_code": 1,
              "output_tail": _output(test_grind_starts_at_15="FAILED", test_stepper_stops_at_the_ends="PASSED")}
    assert judge(ASKED, report) == [f"{OTHER} passes on the base commit: it does not reproduce the bug"]
    assert judge(ASKED, {"reason": "the base commit could not be checked out"}) == [
        "the confirmed tests could not run on the base commit (the base commit could not be checked out)"]
    assert judge(ASKED, None) == ["the confirmed tests could not run on the base commit (it did not run)"]
    assert judge(None, None) == []  # nothing asked, nothing judged


def test_only_a_class_that_asks_for_it_sends_the_base_run_to_the_device():
    def run(classes: dict) -> SimpleNamespace:
        return SimpleNamespace(context={"base_sha": "b" * 40, "confirmed_tests": [TEST],
                                        "size_class": {"class": "small", "classes": {"small": classes}}})

    assert request(run({"red_on_base": True})) == {"base": "b" * 40, "tests": [TEST], "files": ["tests/test_grind.py"],
                                                   "report_env": all_report_env(), "only_files": only_files_specs()}
    assert request(run({})) is None


def test_every_changed_test_file_runs_on_the_base_and_one_without_a_named_test_keeps_the_pipeline_red():
    """A corrected existing test counts when it fails on the base; a changed test file whose tests nobody named
    (a weakened test) is caught."""
    patch = ("diff --git a/app/tests/test_grind.py b/app/tests/test_grind.py\n"
             "diff --git a/app/tests/test_other.py b/app/tests/test_other.py\n"
             "diff --git a/app/grind.py b/app/grind.py\n")
    run = SimpleNamespace(context={"base_sha": "b" * 40, "confirmed_tests": [TEST, OTHER],
                                   "device_change": {"patch": patch},
                                   "size_class": {"class": "small", "classes": {"small": {"red_on_base": True}}}})
    asked = request(run, "app")
    assert asked["files"] == ["tests/test_grind.py", "tests/test_other.py"]
    assert asked["changed"] == ["tests/test_grind.py", "tests/test_other.py"]
    report = {"command": "pytest -v tests/test_grind.py tests/test_other.py", "exit_code": 1,
              "output_tail": _output(test_grind_starts_at_15="FAILED", test_stepper_stops_at_the_ends="FAILED")}
    assert judge(asked, report) == ["tests/test_other.py changed, but none of its tests is in the reproduction: name "
                                    "the tests that show the bug, or undo the change"]


async def _at_pipeline_with_base_run(db, monkeypatch, extra: dict | None = None):
    from app.services.workflow_runs import pipeline
    from app.services.workflow_runs.binding import run_turn_resolution
    from app.services.workflow_runs.records import new_chat_session, start_run
    from tests.phased_workflow_fixtures import admin_user, phase_turn, publish_phased, run_workspace
    from tests.workflow_run_pipeline_support import COMMANDS, _definition

    async def commands(_db, _run):
        return list(COMMANDS), []

    async def device(_db, _run):
        return "device"

    async def no_turn(_db, _run, _node):
        return None

    monkeypatch.setattr(pipeline, "commands_for", commands)
    monkeypatch.setattr("app.services.workflow_runs.workspace.preparation.runtime_of", device)
    monkeypatch.setattr("app.services.workflow_runs.octryx.continuation.runtime_step_entered", no_turn)
    definition = {**_definition(), "size_classes": {"default": "small", "rules": [],
                                                    "classes": {"small": {"red_on_base": True, **(extra or {})}}}}
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=session)
    run.context = {**dict(run.context or {}), "base_sha": "b" * 40, "confirmed_tests": [TEST]}
    await phase_turn(db, session.id, await run_turn_resolution(db, session, user_message="Fix it."),
                     ["knowledge_search"])
    return run, session


@pytest.mark.asyncio
async def test_the_pipeline_asks_the_device_for_the_base_run_and_stays_red_when_a_test_passes_there(db, monkeypatch):
    from app.services.workflow_runs import pipeline, pipeline_failure, pipeline_report
    from tests.workflow_run_pipeline_support import _report

    run, session = await _at_pipeline_with_base_run(db, monkeypatch)
    view = pipeline.contract_view(run)
    assert view["red_on_base"] == {"base": "b" * 40, "tests": [TEST], "files": ["tests/test_grind.py"],
                                   "report_env": all_report_env(), "only_files": only_files_specs()}
    report = {**_report(run, [0, 0]), "red_on_base": {
        "command": "pytest -v tests/test_grind.py", "exit_code": 0, "seconds": 1.0,
        "output_tail": _output(test_grind_starts_at_15="PASSED")}}
    assert await pipeline_report.record_report(db, run, report, session_id=session.id) == "red"
    assert pipeline_failure.failure_for_agent(run)["red_on_base"] == [
        f"{TEST} passes on the base commit: it does not reproduce the bug"]
    assert run.context["red_on_base"]["state"] == "not_proven"  # one place for every gate


@pytest.mark.asyncio
async def test_a_base_run_the_environment_could_not_do_pauses_and_never_reaches_the_agent(db, monkeypatch):
    """A failed setup on the base is the device's problem (``environment_not_ready`` with the remedy), not a reason
    to send the agent back; with a red suite the agent hears only the suite."""
    from app.services.workflow_runs import pipeline_failure, pipeline_report
    from tests.workflow_run_pipeline_support import _report

    run, session = await _at_pipeline_with_base_run(db, monkeypatch)
    setup = {"reason": "the app folder's setup failed on the base commit", "command": "pytest -v tests/test_grind.py"}
    assert await pipeline_report.record_report(db, run, {**_report(run, [0, 0]), "red_on_base": setup},
                                        session_id=session.id) == "red"
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "environment_not_ready", "pipeline")

    run, session = await _at_pipeline_with_base_run(db, monkeypatch)
    assert await pipeline_report.record_report(db, run, {**_report(run, [0, 1]), "red_on_base": setup},
                                        session_id=session.id) == "red"
    assert run.current_node_id == "work" and "red_on_base" not in pipeline_failure.failure_for_agent(run)


def test_the_verdict_is_kept_in_the_shape_the_reproduces_gate_reads():
    from app.services.workflow_runs.red_on_base import record

    run = SimpleNamespace(context={})
    asked = {**ASKED, "changed": ["tests/test_grind.py", "tests/test_other.py"]}
    report = {"command": "pytest -v", "exit_code": 1,
              "output_tail": _output(test_grind_starts_at_15="FAILED", test_stepper_stops_at_the_ends="PASSED")}
    record(run, asked, report, node_id="repro_check", entry=7)
    kept = run.context["red_on_base"]
    assert kept["tests"] == {TEST: "failed", OTHER: "passed"} and kept["state"] == "not_proven"
    assert (kept["base"], kept["node_id"], kept["entry"]) == ("b" * 40, "repro_check", 7)
    assert kept["files_changed"] == ["tests/test_grind.py", "tests/test_other.py"]
    assert kept["unnamed_changes"] == ["tests/test_other.py"] and "passes on the base commit" in kept["reason"]
    record(run, ASKED, {"reason": "timed out after 900 s"}, node_id="repro_check", entry=8,
           environment="the device could not run the tests on the base commit: timed out after 900 s")
    assert run.context["red_on_base"]["state"] == "environment"
    assert run.context["red_on_base"]["tests"] == {TEST: "missing", OTHER: "missing"}


def _reproduce_with_base_run() -> dict:
    from tests.hands_on_support import _reproduce_definition

    definition = _reproduce_definition()
    node = next(item for item in definition["nodes"] if item["id"] == "hands_on")
    node["config"]["red_on_base"] = True
    return definition


async def _at_reproduce_check(db, monkeypatch):
    from app.services.workflow_runs.binding import run_turn_resolution
    from app.services.workflow_runs.phase_outputs import OUTPUTS_KEY
    from app.services.workflow_runs.records import new_chat_session, start_run
    from tests.phased_workflow_fixtures import admin_user, phase_turn, publish_phased, run_workspace

    async def device(_db, _run):
        return "device"

    async def file(_db, _run):
        return {"file": "web/.octryx/environment.json", "app_folder": "web"}

    async def turn(_db, _run, _node):
        return None

    monkeypatch.setattr("app.services.workflow_runs.workspace.preparation.runtime_of", device)
    monkeypatch.setattr("app.services.workflow_runs.pipeline.environment_file_for", file)
    monkeypatch.setattr("app.services.workflow_runs.octryx.continuation.runtime_step_entered", turn)
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _reproduce_with_base_run()),
                          project_id=workspace_id,
                          session=session)
    run.context = {**dict(run.context or {}), "base_sha": "b" * 40,
                   OUTPUTS_KEY: {"reproduction": {"record": {"tests": [TEST]}}}}
    await phase_turn(db, session.id, await run_turn_resolution(db, session, user_message="Go."),
                     ["knowledge_search"])
    return run, session


@pytest.mark.asyncio
async def test_the_reproduce_check_proves_the_submitted_tests_on_the_base_before_any_fix(db, monkeypatch):
    """In a full flow the base run belongs before the fix builds on the reproduction."""
    from app.services.workflow_runs.hands_on import step

    run, session = await _at_reproduce_check(db, monkeypatch)
    view = step.contract_view(run)
    assert view["red_on_base"] == {"base": "b" * 40, "tests": [TEST], "files": ["tests/test_grind.py"],
                                   "report_env": all_report_env(), "only_files": only_files_specs()}
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran",
              "scenarios": [{"id": "repo:tests/hands_on/bugs/OCX-1.json#1", "passed": False,
                             "failed_op": "expect_text", "error": "'15' is not shown"}],
              "red_on_base": {"command": "pytest -v", "exit_code": 1,
                              "output_tail": _output(test_grind_starts_at_15="FAILED")}}
    assert await step.record_report(db, run, report, session_id=session.id) == "reproduced"
    assert (run.context["red_on_base"]["state"], run.context["red_on_base"]["tests"]) == ("proven", {TEST: "failed"})


@pytest.mark.asyncio
async def test_a_base_run_the_device_could_not_do_pauses_the_reproduce_check(db, monkeypatch):
    from app.services.workflow_runs.hands_on import step

    run, session = await _at_reproduce_check(db, monkeypatch)
    view = step.contract_view(run)
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "no_scenarios",
              "red_on_base": {"reason": "the base commit could not be checked out"}}
    assert await step.record_report(db, run, report, session_id=session.id) == "environment"
    assert (run.status, run.pause_reason) == ("paused", "environment_not_ready")
    assert run.context["red_on_base"]["state"] == "environment"


DEMO = "tests/test_pricing.py::PricingTest::test_discount_percent_is_a_percentage_of_the_subtotal"
DEMO_ASKED = {"base": "b" * 40, "tests": [DEMO], "files": ["tests/test_pricing.py"]}
# The device appends the file to the repository's discover command.
APPENDED = {"command": "python3 -m unittest discover -s tests tests/test_pricing.py", "exit_code": 1,
            "output_tail": ("Traceback (most recent call last):\n  File \"unittest/loader.py\", line 346, in discover\n"
                            "    raise ImportError('Start directory is not importable: %r' % start_dir)\n"
                            "ImportError: Start directory is not importable: 'tests/test_pricing.py'\n")}
# The same base run by the python stack's discover template (``{test} -v -p {basename}``), its real output: the
# tests are named relative to the start folder (``test_pricing.PricingTest``).
TEMPLATED = {"command": "python3 -m unittest discover -s tests -v -p test_pricing.py", "exit_code": 1,
             "output_tail": (
    'test_a_discount_above_100_percent_is_refused (test_pricing.PricingTest) ... ok\n'
    'test_an_empty_order_costs_nothing (test_pricing.PricingTest) ... ok\n'
    'test_discount_percent_is_a_percentage_of_the_subtotal (test_pricing.PricingTest) ... FAIL\n'
    'test_subtotal_adds_every_line (test_pricing.PricingTest) ... ok\n'
    'test_total_without_discount_is_the_subtotal (test_pricing.PricingTest) ... ok\n'
    '\n'
    '======================================================================\n'
    'FAIL: test_discount_percent_is_a_percentage_of_the_subtotal (test_pricing.PricingTest)\n'
    '----------------------------------------------------------------------\n'
    'Traceback (most recent call last):\n'
    '  File "tests/test_pricing.py", line 22, in test_discount_percent_is_a_percentage_of_the_subtotal\n'
    '    self.assertEqual(order_total([Line("mug", 50.00)], discount_percent=10), 45.00)\n'
    'AssertionError: 40.0 != 45.0\n'
    '\n'
    '----------------------------------------------------------------------\n'
    'Ran 5 tests in 0.001s\n'
    '\n'
    'FAILED (failures=1)\n')}


def test_each_runner_runs_only_its_files_by_a_template_and_unittest_discover_keeps_its_start_folder():
    specs = [spec for spec in only_files_specs() if ["python3", "-m", "unittest"] in spec["commands"]]
    assert [(spec.get("contains"), spec.get("single_file"), spec["argv"]) for spec in specs] == [
        ("discover", True, "{test} -v -p {basename}"), (None, None, "{prefix} -v {modules}")]
    assert [spec.get("lacks") for spec in specs] == [None, "discover"]  # discover never takes the module form
    templates = {tuple(command): spec["argv"] for spec in only_files_specs() for command in spec["commands"]}
    assert templates[("pytest",)] == templates[("node", "--test")] == templates[("flutter", "test")] == "{test} {files}"
    assert ("npm", "test") not in templates  # no template: the device runs the full command


def test_a_base_run_that_started_no_test_says_so_and_the_templated_one_proves_the_reproduction():
    assert outcomes(DEMO_ASKED, APPENDED) == {DEMO: "missing"}
    why = no_test_started(APPENDED)
    assert why.startswith("the base run started no test (`python3 -m unittest discover -s tests tests/test_pricing.py`")
    assert "Start directory is not importable" in why
    leaked = {**APPENDED, "output_tail": APPENDED["output_tail"] + "password=s3cr3t-value-42\n"}
    assert "s3cr3t-value-42" not in no_test_started(leaked)  # shown to people: redacted like the review
    run = SimpleNamespace(context={})
    record(run, DEMO_ASKED, APPENDED, node_id="pipeline", entry=11)
    assert run.context["red_on_base"]["state"] == "unattributed"
    assert run.context["red_on_base"]["reason"] == why

    assert no_test_started(TEMPLATED) == "" and judge(DEMO_ASKED, TEMPLATED) == []
    record(run, DEMO_ASKED, TEMPLATED, node_id="pipeline", entry=12)
    assert run.context["red_on_base"]["state"] == "proven"
