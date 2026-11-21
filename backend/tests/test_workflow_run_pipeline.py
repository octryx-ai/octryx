"""The run's CI pipeline: the declared tests run without the agent; green goes on to the review,
red goes back to the agent with what failed; the screenshots of that run are the review's."""

from __future__ import annotations

import pytest

from app.services.workflow_runs import pipeline, pipeline_failure, pipeline_report
from app.services.workflow_runs.binding import run_turn_resolution
from tests.phased_workflow_fixtures import phase_turn
from tests.workflow_run_pipeline_support import COMMANDS, TASKS, _at_pipeline, _definition, _report

JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="3">
<testcase classname="tests.test_search" name="test_text_search" time="0.1"/>
<testcase classname="tests.test_search.TestCards" name="test_cards" time="0.1"/>
<testcase classname="tests.test_search" name="test_empty" time="0.1"><failure message="assert 1 == 0">x</failure>
</testcase></testsuite></testsuites>"""


def _junit_report(run, codes, xml=JUNIT):
    report = _report(run, codes)
    report["results"][0].update(junit_xml=xml, junit_files=["tests/test_search.py"])
    return report


@pytest.mark.asyncio
async def test_a_green_pipeline_goes_on_and_keeps_what_it_ran(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch)
    view = pipeline.contract_view(run)
    assert run.current_node_id == "pipeline" and view["commands"] == COMMANDS and view["path"] == [".venv/bin"]
    assert await pipeline_report.record_report(db, run, _report(run, [0, 0]), session_id=session.id) == "green"
    assert run.status == "completed" and pipeline.contract_view(run) is None
    runs = run.context["tests"]["runs"]
    assert [entry["source"] for entry in runs[-2:]] == ["pipeline", "pipeline"]


@pytest.mark.asyncio
async def test_a_red_pipeline_goes_back_to_the_agent_with_what_failed(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch)
    assert await pipeline_report.record_report(db, run, _report(run, [0, 1]), session_id=session.id) == "red"
    assert run.current_node_id == "work" and run.status == "running"
    red = pipeline_failure.failure_for_agent(run)
    assert [item["command"] for item in red["failed"]] == [COMMANDS[1]] and red["failed"][0]["output_end"] == "out 1"


@pytest.mark.asyncio
async def test_a_report_for_another_pass_or_with_a_missing_command_never_passes(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch)
    stale = {**_report(run, [0, 0]), "entry": 999}
    assert await pipeline_report.record_report(db, run, stale, session_id=session.id) == "ignored"
    partial = _report(run, [0, 0])
    partial["results"] = partial["results"][:1]  # the system tests did not run
    assert await pipeline_report.record_report(db, run, partial, session_id=session.id) == "red"


def test_the_run_card_shows_the_screenshots_the_review_takes():
    from types import SimpleNamespace

    from app.services.workflow_runs.review.screens import reviewed_phase

    review = SimpleNamespace(id="independent_review", kind="review",
                             config={"phase": "implement", "screens_node": "pipeline"})
    graph = SimpleNamespace(nodes={"independent_review": review}, order=["independent_review"])
    assert reviewed_phase(SimpleNamespace(context={}), graph) == "pipeline"


def test_a_finished_run_does_not_say_it_waits_and_a_bitbucket_pr_has_its_link():
    """Once the stories are done, the card must not say the run waits for the merge without a PR link."""
    from types import SimpleNamespace

    from app.services.secure_work.pull_requests.record_identity import answered_pull_request
    from app.services.workflow_runs.run_notices import reviewer_notice
    from app.tools.bitbucket_impl._bitbucket_pull_requests import _pr_summary

    pr = {"provider": "bitbucket", "reviewer_skipped": "requester_unresolved", "requester_platform": "bitbucket_server"}
    done = reviewer_notice(SimpleNamespace(pull_request=pr, status="completed"))
    waiting = reviewer_notice(SimpleNamespace(pull_request=pr, status="waiting"))
    assert "waits for the merge" not in done["text"] and "waits for the merge" in waiting["text"]
    href = "https://bitbucket.example/projects/P/repos/r/pull-requests/41"
    # The Server tool answers the web URL as the string ``links`` (no ``url``).
    assert answered_pull_request(_pr_summary({"id": 41, "links": {"self": [{"href": href}]}})) == ("41", href)


@pytest.mark.asyncio
async def test_a_server_run_skips_the_pipeline_and_says_so(db, monkeypatch):
    """The workflow covers several scenarios; a server run has no pipeline runner yet."""
    run, _session = await _at_pipeline(db, monkeypatch, runtime="server")
    assert run.status == "completed" and run.context["pipeline"]["state"] == "skipped"


@pytest.mark.asyncio
async def test_every_test_of_the_junit_report_is_recorded_and_a_red_one_is_named_to_the_agent(db, monkeypatch):
    """The pipeline must not keep the JUnit report as text, else ``passed_tests`` sees none of its tests and the
    agent hears only the command. Each test is a result, and the failing ids go back to the agent."""
    from app.services.workflow_runs.task_list import passed_tests

    run, session = await _at_pipeline(db, monkeypatch)
    assert await pipeline_report.record_report(db, run, _junit_report(run, [1, 0]), session_id=session.id) == "red"
    results = run.context["tests"]["runs"][-2]["results"]
    assert results["tests/test_search.py::test_empty"]["outcome"] == "failed"
    assert {"tests/test_search.py::test_text_search", "tests/test_search.py::TestCards::test_cards"} <= passed_tests(
        run)
    red = pipeline_failure.failure_for_agent(run)
    assert red["failed"][0]["failed_tests"] == ["tests/test_search.py::test_empty"]
    reason = run.context["actions"]["pipeline"]["reason"]
    assert reason == f"pipeline red: {COMMANDS[0]} failed (tests/test_search.py::test_empty)"


@pytest.mark.asyncio
async def test_green_needs_every_task_proven_by_the_pipeline_and_then_the_tasks_are_done(db, monkeypatch):
    """The pipeline is the one judge of "task proven". A task whose proof test did not pass there
    sends the work back with the list; once every proof passed, the tasks are done (the review verifies them)."""
    run, session = await _at_pipeline(db, monkeypatch)
    run.context = {**run.context, "task_list": [*TASKS, {"id": "T3", "text": "chips",
                                                         "proof": "tests/test_chips.py::test_chips",
                                                         "proofs": ["tests/test_chips.py::test_chips"]}]}
    green_xml = JUNIT.replace('<failure message="assert 1 == 0">x</failure>', "")
    assert await pipeline_report.record_report(db, run, _junit_report(run, [0, 0], green_xml), session_id=session.id) == "red"
    assert run.current_node_id == "work"
    assert [task["status"] for task in run.context["task_list"]] == ["in_progress", "in_progress", "open"]
    red = pipeline_failure.failure_for_agent(run)
    assert red["failed"] == [] and red["missing_proof_tests"] == ["T3 (tests/test_chips.py::test_chips: not run)"]
    assert "missing proof tests: T3 (tests/test_chips.py::test_chips: not run)" in run.context["actions"][
        "pipeline"]["reason"]

    run.context = {**run.context, "task_list": [{**task, "status": "open"} for task in TASKS]}
    await phase_turn(db, session.id, await run_turn_resolution(db, session, user_message="Fix."),
                     ["knowledge_search"])
    assert await pipeline_report.record_report(db, run, _junit_report(run, [0, 0], green_xml), session_id=session.id) == (
        "green")
    assert [task["status"] for task in run.context["task_list"]] == ["done", "done"]


def test_the_pipeline_follows_a_phase_only_with_the_step_and_a_declared_command():
    from app.services.workflow_runs.graph import parse_phased_definition

    graph = parse_phased_definition(_definition())
    assert pipeline.follows(graph, "work", {"test": COMMANDS[0]})
    assert not pipeline.follows(graph, "work", {})  # nothing declared: the step is skipped, the Stop judges
    assert not pipeline.follows(graph, "pipeline", {"test": COMMANDS[0]})


@pytest.mark.asyncio
async def test_the_pipeline_is_red_on_the_code_style_whatever_the_suites_say(db, monkeypatch):
    """The platform enforces the installation's code style itself, on the device's counts of the
    whole change against the run's base; a touched legacy file over the limit only warns."""
    from app.services.code_style.resolve import effective, flat

    run, session = await _at_pipeline(db, monkeypatch)
    style = {"general": flat(effective({}, None)), "languages": {}}
    pipeline._set(run, {**pipeline.state(run), "code_style": style, "base": "a" * 40})
    view = pipeline.contract_view(run)
    assert view["code_style"] == style and view["base"] == "a" * 40  # the device counts against this base
    report = {**_report(run, [0, 0]), "sizes": {"files": {"app/big.py": 900, "app/old.py": 700},
                                                "base_files": {"app/old.py": 700}, "functions": []}}
    assert await pipeline_report.record_report(db, run, report, session_id=session.id) == "red"
    current = pipeline.state(run)
    assert current["code_style_errors"] == ["app/big.py: new file has 900 lines (max 300): split it into smaller "
                                            "modules [max_lines_per_file]"]
    assert current["code_style_warnings"][0].startswith("app/old.py: has 700 lines (max 300)")


def test_a_pipeline_red_only_on_code_style_tells_the_agent_what_to_fix():
    """When only code style is red, the agent's contract names what to fix."""
    from types import SimpleNamespace

    finding = "coffee/flutter/claude/system_test/run_system_test.py:717: E501 Line too long [linter]"
    run = SimpleNamespace(context={pipeline.CONTEXT_KEY: {"state": pipeline.STATE_RED, "results": [
        {"command": "flutter test", "exit_code": 0}], "code_style_errors": [finding]}})
    red = pipeline_failure.failure_for_agent(run)
    assert red["code_style_errors"] == [finding] and "code style" in red["code_style_rule"]
