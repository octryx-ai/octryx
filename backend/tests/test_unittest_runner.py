"""A Python app whose declared test command is ``python -m unittest`` runs its tests for the Stop as well
(when the runners in stacks.json know pytest only, an agent that runs the declared `python -m unittest` by Bash, 1 red
as wanted, still hears "tool_called run_test_suite: The test suite ran" from the reproduce check until it gives up)."""

from __future__ import annotations

from app.models import ToolCall
from app.services.agent_gateway.contract import (
    EXECUTION_OUTCOME_SUCCEEDED,
    TOOL_CALL_EXECUTED_KEY,
    TOOL_CALL_SOURCE_HOOK,
)
from app.services.workflow_checks.test_output import parse
from app.services.workflow_runs.octryx.hooks import test_prefixes as prefixes_of
from app.services.workflow_runs.octryx.stop_evidence import phase_evidence
from app.time_utils import utc_now

VERBOSE = """test_add_item (tests.test_cart.CartTest.test_add_item) ... ok
test_empty (tests.test_cart.CartTest.test_empty) ... ok
test_remove (tests.test_cart.CartTest.test_remove) ... ok
test_total (tests.test_cart.CartTest.test_total) ... ok
test_total_rounds_down (tests.test_cart.CartTest.test_total_rounds_down) ... FAIL

======================================================================
FAIL: test_total_rounds_down (tests.test_cart.CartTest.test_total_rounds_down)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "tests/test_cart.py", line 30, in test_total_rounds_down
AssertionError: 10 != 9

----------------------------------------------------------------------
Ran 5 tests in 0.002s

FAILED (failures=1)
"""


def _bash(command: str, output: str, exit_code: int) -> ToolCall:
    parameters = {"command": command, "source": "model_gateway", "block_index": 0,
                  TOOL_CALL_EXECUTED_KEY: {"source": TOOL_CALL_SOURCE_HOOK, "outcome": EXECUTION_OUTCOME_SUCCEEDED}}
    return ToolCall(session_id="s", tool_name="Bash", parameters=parameters, status="success",
                    result={"exit_code": exit_code, "excerpt": output}, created_at=utc_now())


def test_the_declared_unittest_command_is_a_test_suite_run_with_its_exit_code_and_output():
    for command in ("python -m unittest -v", "python3 -m unittest discover -s tests -v",
                    ".venv/bin/python -m unittest tests.test_cart"):
        evidence = phase_evidence([_bash(command, VERBOSE, 1)], since=None, test_prefixes=prefixes_of(None))
        suite = [use for use in evidence.tools if use.name == "run_test_suite"]
        assert suite and suite[0].succeeded, command  # "the test suite ran", red as the reproduction wants
        assert suite[0].result["exit_code"] == 1 and "Ran 5 tests" in suite[0].result["stdout"]


def test_unittest_s_summary_line_is_no_failed_test_of_its_own():
    """`FAILED (failures=1)` is unittest's summary, not pytest's `FAILED <test id>` (a test named "(failures=1)")."""
    parsed = parse(VERBOSE)
    assert "(failures=1)" not in parsed.results
    # The traceback names the test file, so the failing test resolves.
    assert parsed.results["tests/test_cart.py::CartTest::test_total_rounds_down"]["outcome"] == "failed"


def test_unittest_s_harmless_options_pass_the_shell_policy_also_when_tests_are_protected():
    from app.services.workflow_runs.octryx.shell_rules import strict_shell_allows

    for command in ("python -m unittest -v", "python3 -m unittest discover -s tests -p 'test_*.py' -v",
                    ".venv/bin/python -m unittest -v tests.test_cart.CartTest.test_total_rounds_down"):
        assert strict_shell_allows(command, runs_tests=True, test_prefixes=prefixes_of(None), protected=True), command
    for command in ("python -m unittest -v /etc/passwd", "python -m unittest --catch;id", "python -m unittest -s .."):
        assert not strict_shell_allows(command, runs_tests=True, test_prefixes=prefixes_of(None), protected=True)
