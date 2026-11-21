"""The bug flow from report to "fixed in"."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.services.workflow_runs.bugs.intake import fields_of, report_state
from app.services.workflow_runs.bugs.report import text_for
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.hands_on.reproduce import verdict

SEEDS = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"


def _seed() -> dict:
    return next(seed for seed in json.loads(SEEDS.read_text()) if seed["key"] == "bug-fix-reproduction")["definition"]


def test_the_bug_seed_runs_from_the_report_to_fixed_in():
    definition = _seed()
    assert validate_phased_definition(definition)["errors"] == []
    graph = parse_phased_definition(definition)
    routes = {(edge["source_node_id"], edge.get("when")): edge["target_node_id"] for edge in definition["edges"]}
    # A complete report needs no person; a missing field is one question round.
    assert routes[("start", None)] == "intake_check"
    assert routes[("intake_check", "succeeded")] == "ticket" and routes[("intake_check", "incomplete")] == "intake"
    assert routes[("answers", "confirmed")] == routes[("answers", "changed")] == "ticket"
    # Reproduced on the unchanged app before any fix; a person only without a scenario.
    # The reproduction's tests also run on the base commit before any fix (red_on_base).
    assert graph.nodes["repro_check"].config == {"action": "hands_on.run", "mode": "reproduce", "red_on_base": True}
    assert routes[("reproduce", None)] == "repro_check"
    assert routes[("repro_check", "succeeded")] == "reproduces" and routes[("repro_check", "skipped")] == "confirm_repro"
    assert routes[("repro_check", "failed")] == "reproduce"
    assert routes[("repro_check", "cannot_reproduce")] == "not_reproducible"
    assert routes[("not_reproducible", "succeeded")] == "cannot_reproduce"
    setup_loop = next(edge for edge in definition["edges"] if edge["id"] == "loop-repro-setup")
    assert (setup_loop["kind"], setup_loop["max_iterations"]) == ("loop", 2)
    # Fix, pipeline, hands-on (with the kept scenario), a review that names the root cause.
    assert routes[("green", "passed")] == "pipeline" and routes[("pipeline", "succeeded")] == "hands_on"
    assert routes[("hands_on", "succeeded")] == "independent_review" and routes[("hands_on", "failed")] == "fix"
    assert graph.nodes["independent_review"].config["root_cause"] is True
    # The reporter is told twice.
    assert routes[("pr", "succeeded")] == "report_fix" and routes[("report_fix", "succeeded")] == "in_review"
    assert routes[("merged", "pr.merged")] == "report_released" and routes[("report_released", "succeeded")] == "done"
    assert "tests/hands_on/bugs/<work item key>.json" in graph.nodes["reproduce"].config["workflow_contract"][
        "when_to_use"]


def test_the_report_fields_are_read_from_headings_and_labels():
    complete = ("Grind setting starts at 0.0\n## Steps\n1. Open a new brew\n## Expected\n15\n## Actual\n0.0\n"
                "Environment: Chrome 131, macOS")
    assert sorted(fields_of(complete)) == ["actual", "environment", "expected", "steps"]
    assert report_state(complete)["missing"] == []
    labelled = "Beans gone\n**Steps:** add a bean, reload\n**Expected:** the bean stays\n"
    state = report_state(labelled)
    assert state["missing"] == ["actual", "environment"] and state["screenshot"] is False
    assert report_state("Device rotation loses the bean?\nVersion unknown")["missing"] == ["steps", "expected", "actual",
                                                                           "environment"]


def test_reproduced_needs_the_symptom_a_setup_failure_is_never_cannot_reproduce():
    def report(*results, state="ran"):
        return {"state": state, "scenarios": list(results)}

    assert verdict(report({"id": "a", "passed": False, "failed_op": "expect_text", "error": "'15' is not shown"}))[
        0] == "reproduced"
    assert verdict(report({"id": "a", "passed": True}))[0] == "cannot_reproduce"
    assert verdict(report({"id": "a", "passed": False, "failed_op": "click", "error": "nothing shows 'Add'"}))[
        0] == "setup_failed"
    assert verdict({"state": "unavailable", "problem": "the app exited"}) == ("setup_failed", "the app exited")
    assert verdict({"state": "no_scenarios"})[0] == "no_scenarios"



def test_only_a_red_symptom_step_reproduces_a_bug():
    """A scenario that fails at "'M1' is not shown" while it still adds its grinder does not count as reproduced.
    Only the symptom step (marked, else the last expect) reproduces."""
    def report(item):
        return {"state": "ran", "scenarios": [{"id": "OCX-72#1", "passed": False, **item}]}

    early = {"failed_op": "expect_text", "failed_step": 10, "failed_symptom": False, "symptom_step": 14,
             "error": "'M1' is not shown"}
    outcome, why = verdict(report(early))
    assert outcome == "setup_failed" and "step 11 (expect_text) failed before the symptom steps from 15" in why
    at_symptom = {**early, "failed_step": 14, "failed_symptom": True, "error": "'15.0' is not shown"}
    assert verdict(report(at_symptom))[0] == "reproduced"


def test_the_reporter_reads_the_cause_the_pull_request_and_fixed_in():
    run = SimpleNamespace(ticket_key="CAF-61", title="Grind setting", pull_request={
        "url": "https://example.invalid/pr/7", "merge_commit_sha": "abc123def4567890"}, context={
        "review": {"summary": "Root cause: lib/brew.dart:12 - the default is 0.0. The fix sets 15."},
        "hands_on_reproduce": {"reason": "S1 passed", "results": [
            {"passed": False, "screenshots": ["hands-on-repo-failed.png"]}]},
        "hands_on": {"results": [{"passed": True, "screenshots": ["hands-on-s1-end.png"]}]}})
    fixed = text_for(run, "fixed")
    assert "Root cause: lib/brew.dart:12" in fixed and "https://example.invalid/pr/7" in fixed
    assert "Before (reproduced): hands-on-repo-failed.png" in fixed and "After (green): hands-on-s1-end.png" in fixed
    assert text_for(run, "released").startswith("CAF-61: fixed in abc123def456")
    assert "not fixed blindly" in text_for(run, "cannot_reproduce")
