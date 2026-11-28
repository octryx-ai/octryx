"""The workflow checks judge a test run by its FULL result, never the model's compacted copy."""

from __future__ import annotations

import pytest

from app.services.workflow_checks.evidence import FULL_RESULT_KEY, MISSING_FULL_RESULT, tool_uses, turn_evidence
from app.services.workflow_checks.library import evaluate_checks
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

CASES = 300  # parametrized cases: the result is far beyond the model-facing budget
TOOL_CALL = {"content": "", "tool_calls": [{"id": "call-tests", "function": {"name": "run_test_suite",
                                                                              "arguments": "{}"}}]}
FINAL = {"content": "The new tests fail as expected; the existing ones pass."}
RAN_CHECK = {"type": "tool_called", "params": {"tools": ["run_test_suite"]}, "blocking": True,
             "description": "The test suite ran"}


def test_a_history_entry_with_only_the_compacted_copy_is_not_verified():
    compacted = {"_hard_capped": True, "keys": ["stdout", "test_report"], "preview": "15 passed",
                 "_prompt_result_source": "compact_result"}
    history = [{"tool_name": "run_test_suite", "params": {}, "result": compacted}]

    uses = tool_uses(history)
    assert uses[0].succeeded is False and uses[0].result["error"] == MISSING_FULL_RESULT
    evidence = turn_evidence(history)
    assert evidence.test_runs == []
    assert [result.outcome for result in evaluate_checks([RAN_CHECK], evidence)] == ["failed"]


def test_the_full_result_on_the_entry_is_what_the_checks_judge():
    full = {"exit_code": 1, "all_green": False, "command": "python -m pytest -v tests/",
            "stdout": "tests/test_a.py::test_new FAILED\ntests/test_a.py::test_old PASSED\n1 failed, 1 passed in 0.1s",
            "stderr": "", "failed_tests": ["tests/test_a.py::test_new"]}
    history = [{"tool_name": "run_test_suite", "params": {}, "result": {"_hard_capped": True},
                FULL_RESULT_KEY: full}]

    evidence = turn_evidence(history)

    assert [result.outcome for result in evaluate_checks([RAN_CHECK], evidence)] == ["passed"]
    assert evidence.test_runs[0]["results"]["tests/test_a.py::test_new"]["outcome"] == "failed"
    assert tool_uses([{"tool_name": "read_workspace_file", "result": {"_hard_capped": True}}])[0].succeeded is True


