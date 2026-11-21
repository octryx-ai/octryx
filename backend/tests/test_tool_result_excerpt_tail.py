"""A long tool result keeps its tail: pytest's summary decides whether the tests ran."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

from app.services.model_gateway.inbound.transcript_tools import MAX_TOOL_RESULT_EXCERPT_CHARS, result_excerpt
from app.services.workflow_checks.test_results import DEFAULT_TEST_PREFIXES
from app.services.workflow_runs.octryx.stop_evidence import phase_evidence

OUTPUT = ("FFFFF" + " " * 60 + "[100%]\n=== FAILURES ===\n" + ("E   AssertionError: greeting.py is missing\n" * 200)
          + "=========================== short test summary info ============================\n"
          + "FAILED test_greeting.py::test_greet_returns_hello_name - AssertionError\n5 failed in 0.02s\n")


def test_a_long_result_keeps_head_and_tail():
    excerpt = result_excerpt(OUTPUT)
    assert len(excerpt) < MAX_TOOL_RESULT_EXCERPT_CHARS + 40
    assert excerpt.startswith("FFFFF") and excerpt.rstrip().endswith("5 failed in 0.02s")


def test_a_failing_test_run_with_long_output_counts_as_a_run():
    row = SimpleNamespace(tool_name="Bash", status="error", created_at=datetime.datetime(2026, 11, 9, 18),
                          parameters={"command": ".venv/bin/python -m pytest -q"},
                          result={"is_error": True, "excerpt": "Exit code 1\n" + result_excerpt(OUTPUT)})
    evidence = phase_evidence([row], since=None, test_prefixes=DEFAULT_TEST_PREFIXES)
    assert [use.name for use in evidence.tools] == ["run_test_suite"]
