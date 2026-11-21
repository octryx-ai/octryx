"""A changing phase is finished only when the app's system tests (Playwright, like CI) pass on the running app
(unit tests can look done while the app's checklist PUT hangs)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models import ToolCall
from app.services.workflow_runs.octryx.declared_commands import declared_commands
from app.services.workflow_runs.octryx.stop_evidence import phase_evidence
from app.services.workflow_runs.octryx.system_tests import (
    phase_system_tests,
    rule_text,
    summary_counts,
    system_command,
    system_tests_result,
)
from app.services.workflow_runs.workspace.spec import (
    declared_environment,
    runtime_environment,
    validate_environment,
)

SYSTEM = ".venv/bin/python -m pytest -v tests/system"
RULE = rule_text(SYSTEM)  # the catalog's run.system_tests.rule with this command's full-run options
UNIT = ".venv/bin/python -m pytest -v --ignore=tests/system"
START = datetime(2026, 11, 11, 13, 0)


def _bash(command: str, *, green: bool, minute: int, excerpt: str = "") -> ToolCall:
    return ToolCall(id=f"t{minute}", session_id="s", tool_name="Bash", status="success" if green else "error",
                    parameters={"input": {"command": command}, "command": command},
                    result={"is_error": not green, "excerpt": excerpt}, created_at=START + timedelta(minutes=minute))


def test_the_repository_declares_its_system_test_command():
    setup = {"test_commands": [UNIT], "system_test_commands": [SYSTEM]}
    environment = declared_environment(setup)
    assert environment["system_test"] == SYSTEM
    assert runtime_environment(environment)["system_test"] == SYSTEM
    assert SYSTEM in declared_commands(environment)  # runs verbatim in a changing phase
    declared, errors = validate_environment({"test": UNIT, "system_test": SYSTEM})
    assert not errors and declared["system_test"] == SYSTEM
    assert "system_test" not in runtime_environment(declared_environment({"test_commands": [UNIT]}))


def test_only_a_changing_phase_gets_the_system_tests():
    environment = {"test": UNIT, "system_test": SYSTEM}
    assert phase_system_tests("change", environment) == {"command": SYSTEM, "rule": RULE}
    assert phase_system_tests("read", environment) is None
    assert phase_system_tests("change", {"test": UNIT}) is None
    assert system_command({"phase": {"system_tests": {"command": SYSTEM}}}) == (SYSTEM,)


def test_the_last_system_test_run_of_the_pass_must_be_green():
    system = {"command": SYSTEM, "rule": RULE}
    never = system_tests_result(system, [_bash(UNIT, green=True, minute=1)], START)
    assert never.blocking and "never run" in never.description
    red = system_tests_result(system, [_bash(SYSTEM, green=True, minute=1),
                                       _bash(SYSTEM, green=False, minute=2, excerpt="FAILED test_tick - Timeout 5000ms")],
                              START)
    assert red.blocking and "Timeout 5000ms" in red.description
    assert system_tests_result(system, [_bash(SYSTEM, green=False, minute=1), _bash(SYSTEM, green=True, minute=2)],
                               START) is None
    old = [_bash(SYSTEM, green=True, minute=-5)]
    assert "never run" in system_tests_result(system, old, START).description  # an earlier pass does not count
    assert system_tests_result(None, [], START) is None


def test_a_system_test_run_is_not_the_unit_test_evidence():
    rows = [_bash(UNIT, green=True, minute=1), _bash(SYSTEM, green=False, minute=2)]
    evidence = phase_evidence(rows, since=START, test_prefixes=((".venv/bin/python", "-m", "pytest"),),
                              system=(SYSTEM,))
    assert [use.name for use in evidence.tools][-1] == "run_system_tests"
    assert len(evidence.test_runs) <= 1  # only the unit test run is a test run


def test_a_green_run_that_skipped_its_system_tests_does_not_count():
    # A model may mark every system test skipped when the sandbox blocks the browser.
    system = {"command": SYSTEM, "rule": RULE}
    skipped = _bash(SYSTEM, green=True, minute=1, excerpt="===== 3 skipped in 0.35s =====")
    result = system_tests_result(system, [skipped], START)
    assert result.blocking and "never skip" in result.description
    partly = _bash(SYSTEM, green=True, minute=2, excerpt="===== 2 passed, 1 skipped in 1.2s =====")
    assert system_tests_result(system, [partly], START).blocking
    passed = _bash(SYSTEM, green=True, minute=3, excerpt="===== 3 passed in 3.26s =====")
    assert system_tests_result(system, [skipped, passed], START) is None
    assert summary_counts("x\n== 2 passed, 1 skipped, 1 error in 2s ==") == {"passed": 2, "skipped": 1, "error": 1}


def test_a_product_change_without_a_system_test_does_not_finish_the_phase():
    # A model builds the checklist API, runs only the two existing system tests, and must not pass.
    from app.services.workflow_runs.octryx.system_tests import changed_files, uncovered_change

    def patch(*names):
        return {"base": "a" * 40, "patch": "".join(f"diff --git a/{n} b/{n}\n+x\n" for n in names)}

    product = patch("src/packmate/api/checklist.py", "tests/test_checklist_api.py", "packmate/SPEC.md")
    assert changed_files(product) == ["packmate/SPEC.md", "src/packmate/api/checklist.py",
                                      "tests/test_checklist_api.py"]
    assert "no system test in tests/system/" in uncovered_change(SYSTEM, product)
    covered = patch("src/packmate/api/checklist.py", "tests/system/test_checklist_system.py")
    assert uncovered_change(SYSTEM, covered) == ""
    assert uncovered_change(SYSTEM, patch("packmate/SPEC.md", "tests/test_x.py")) == ""  # no product change
    assert uncovered_change(SYSTEM, {"base": "a", "base_unavailable": True}) == ""  # cannot judge
    assert uncovered_change(SYSTEM, {**product, "truncated": True}) == ""

    system = {"command": SYSTEM, "rule": RULE}
    green = [_bash(SYSTEM, green=True, minute=1, excerpt="===== 2 passed in 1.9s =====")]
    assert system_tests_result(system, green, START, change=product).blocking
    assert system_tests_result(system, green, START, change=covered) is None


def test_a_system_test_that_does_nothing_does_not_count():
    # A placeholder test with only ``pass``.
    from app.services.workflow_runs.octryx.system_tests import empty_tests

    patch = ("diff --git a/tests/system/test_corpus_system.py b/tests/system/test_corpus_system.py\n"
             "+def test_starts(benchmark_url, playwright):\n+    api = playwright.request.new_context()\n"
             "+    assert api\n+\n"
             "+def test_fails_with_invalid_corpus():\n+    # covered by unit tests\n+    pass\n"
             "diff --git a/src/benchmark/run.py b/src/benchmark/run.py\n+def test_not_a_system_test():\n+    pass\n")
    change = {"base": "a" * 40, "patch": patch}
    assert empty_tests(SYSTEM, change) == ["tests/system/test_corpus_system.py::test_fails_with_invalid_corpus"]
    system = {"command": SYSTEM, "rule": RULE}
    green = [_bash(SYSTEM, green=True, minute=1, excerpt="===== 2 passed in 1.9s =====")]
    result = system_tests_result(system, green, START, change=change)
    assert result.blocking and "check nothing" in result.description


def test_a_system_test_without_an_assertion_does_not_count():
    # A test that fills the input, takes a screenshot and checks nothing.
    from app.services.workflow_runs.octryx.system_tests import empty_tests

    patch = ("diff --git a/tests/system/test_search_system.py b/tests/system/test_search_system.py\n"
             "+def test_search_text_filter(page, benchmark_url, shot):\n+    page.goto(benchmark_url)\n"
             "+    page.fill(\"input[name='q']\", \"a\")\n+    shot(page, \"search-text-results\")\n+\n"
             "+def test_cards(page, benchmark_url):\n+    page.goto(benchmark_url)\n"
             "+    expect(page.locator('.dish-card').first).to_be_visible()\n")
    found = empty_tests(SYSTEM, {"base": "a" * 40, "patch": patch})
    assert found == ["tests/system/test_search_system.py::test_search_text_filter"]


def test_the_system_test_rule_goes_only_to_phases_that_may_write_the_system_test_folder():
    """The rule ("add or extend a test in the system test folder") does not reach backend and frontend items whose
    paths exclude tests/system/**, nor the coordinator (docs/stories/** only)."""
    environment = {"test": UNIT, "system_test": SYSTEM}
    wanted = {"command": SYSTEM, "rule": RULE}
    assert phase_system_tests("change", environment, write=[]) == wanted  # no path rules: it may write anything
    assert phase_system_tests("change", environment, write=["tests/system/**"]) == wanted
    assert phase_system_tests("change", environment, write=["tests/**", "src/**"]) == wanted
    assert phase_system_tests("change", environment, write=["e2e/**"], role="test") == wanted  # the test role
    assert phase_system_tests("change", environment, write=["docs/stories/**"]) is None  # the coordinator
    assert phase_system_tests("change", environment, write=["src/kitchen-helper/api/**", "tests/test_api.py"],
                              role="backend") is None
    assert phase_system_tests("change", environment, write=["web/**"], role="frontend") is None
