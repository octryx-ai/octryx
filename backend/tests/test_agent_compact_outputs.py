"""The agent's views of the run contract and of a long test run stay small and keep what it
must act on (``octryx/compact_view``, ``workflow_checks/test_brief``)."""

from __future__ import annotations

from app.services.engineering_knowledge.stacks import built_in
from app.services.workflow_checks.test_brief import brief
from app.services.workflow_runs.octryx.compact_view import DETAIL_PATHS, PATHS_KEY, compact

APP = "/repo/coffee/flutter/claude"


def _contract() -> dict:
    return {
        "run": {"id": "r-1"}, "digest": "sha256:x", "preparation": {"branch": "b", "environment": {"test": "t"}},
        "work_item": {"key": "OCX-90", "description": "long text"}, PATHS_KEY: list(DETAIL_PATHS),
        "phase": {"title": "Minimal fix", "code_style": {"languages": {"dart": {"linter": {"command": "x" * 5000}}}},
                  "code_style_brief": "Style rules", "previous_change": "diff", "agent": {"instructions": "i"},
                  "tools": {"on_device": ["Edit"], "allow": ["edit_workspace_file"], "deny": ["bash"]},
                  "findings": ["The suite is green"], "product_owner_answers": ["Start at 15"],
                  "inputs": {"reproduction": {"tests": ["test/a_test.dart::starts at 15"]}}},
        "loop": [{"title": "Fix ↔ test", "iteration": 2, "of": 4}],
    }


def test_the_compact_contract_drops_the_launchers_detail_and_keeps_what_the_agent_acts_on():
    view = compact(_contract())
    phase = view["phase"]
    assert "code_style" not in phase and "previous_change" not in phase and "agent" not in phase
    assert phase["tools"] == {"on_device": ["Edit"], "allow": ["edit_workspace_file"]}  # e.g. its submit tools
    assert "preparation" not in view and PATHS_KEY not in view
    assert view["work_item"]["key"] == "OCX-90"  # a fresh phase session learns the item's criteria here
    assert phase["findings"] == ["The suite is green"] and phase["product_owner_answers"] == ["Start at 15"]
    assert phase["inputs"]["reproduction"]["tests"] == ["test/a_test.dart::starts at 15"]
    assert "phase.code_style" in view["detail_omitted"] and "detail=true" in view["detail_omitted"]


def _flutter_output(failing: bool) -> str:
    lines = [f"00:00 +0: loading {APP}/test/features/brews/brew_form_test.dart"]
    lines += [f"00:01 +{i}: {APP}/test/features/brews/brew_form_test.dart: case {i} keeps its value"
              for i in range(400)]
    if failing:
        lines += [f"00:02 +400: {APP}/test/features/brews/brew_form_test.dart: OCX-90 grind starts at 15 [E]",
                  "  Expected: '15.0'", "    Actual: '1.0'", "  package:matcher expect",
                  "00:03 +400 -1: Some tests failed."]
    else:
        lines += ["00:03 +400: All tests passed!"]
    return "\n".join(lines)


def test_a_long_red_flutter_run_reaches_the_agent_as_its_summary_and_the_failing_test_with_its_message():
    text = brief("cd coffee/flutter/claude && flutter test", _flutter_output(True))
    assert "1 failed" in text and "The full report is with the platform." in text
    assert "test/features/brews/brew_form_test.dart::OCX-90 grind starts at 15" in text
    assert "Expected: '15.0' Actual: '1.0'" in text
    assert len(text) <= built_in()["general"]["test_brief"]["max_chars"]


def test_a_long_green_run_is_its_summary_only_and_short_or_other_commands_get_no_brief():
    green = brief("flutter test", _flutter_output(False))
    assert "failed" not in green and green.count("\n") == 0 and "passed" in green
    assert brief("flutter test", "00:01 +1: All tests passed!") == ""  # the agent reads a short run whole
    assert brief("git log", _flutter_output(True)) == ""


def test_a_runners_own_limits_from_the_stack_data_win():
    stacks = built_in()
    stacks["stacks"]["flutter"]["test_runner"]["brief"] = {"min_chars": 10, "message_chars": 8}
    text = brief("flutter test", _flutter_output(True), stacks)
    assert "Expected" in text and "Actual" not in text
