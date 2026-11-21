"""The declared test command must pass after the pass's last change: running only the new test files is not
enough when the declared command fails (e.g. on an import file mismatch)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models import ToolCall
from app.services.workflow_runs.octryx.declared_suite import declared_suite_result

UNIT = ".venv/bin/python -m pytest -v --ignore=tests/system"
START = datetime(2026, 11, 11, 17, 0)
CONTRACT = {"phase": {"capability_class": "change"}, "preparation": {"environment": {"test": UNIT}}}


def _row(minute, tool, *, command=None, green=True, path=None):
    data = {"command": command} if command else {"file_path": path or "src/a.py"}
    return ToolCall(id=f"t{minute}{tool}", session_id="s", tool_name=tool, status="success" if green else "error",
                    parameters={"input": data}, result={"is_error": not green},
                    created_at=START + timedelta(minutes=minute))


def test_only_single_files_after_the_last_edit_do_not_finish_the_phase():
    rows = [_row(1, "Edit"), _row(2, "Bash", command=".venv/bin/python -m pytest -v tests/benchmark/test_x.py")]
    result = declared_suite_result(CONTRACT, rows, START)
    assert result.blocking and "did not run in full after the last change" in result.description


def test_the_declared_command_green_after_the_last_change_passes():
    rows = [_row(1, "Bash", command=UNIT, green=False), _row(2, "Write"), _row(3, "Bash", command=UNIT)]
    assert declared_suite_result(CONTRACT, rows, START) is None


def test_a_red_last_run_or_a_change_after_the_run_fails():
    red = [_row(1, "Edit"), _row(2, "Bash", command=UNIT, green=False)]
    assert "failed in its last full run" in declared_suite_result(CONTRACT, red, START).description
    late = [_row(1, "Bash", command=UNIT), _row(2, "Bash", command="git restore tests/test_matching.py")]
    assert declared_suite_result(CONTRACT, late, START).blocking  # a restore is a change too


def test_no_change_no_declared_command_or_a_read_phase_is_not_judged():
    assert declared_suite_result(CONTRACT, [_row(1, "Bash", command="ls")], START) is None
    assert declared_suite_result({"phase": {"capability_class": "change"}}, [_row(1, "Edit")], START) is None
    read = {**CONTRACT, "phase": {"capability_class": "read"}}
    assert declared_suite_result(read, [_row(1, "Edit")], START) is None


def test_a_documentation_only_change_needs_no_test_run():
    # A spec draft changes only benchmark/SPEC.md, may not run tests, and pauses.
    from app.services.workflow_runs.octryx.system_tests import docs_only, system_tests_result

    spec = [_row(1, "Edit", path="benchmark/SPEC.md"), _row(2, "Write", path="docs/notes.txt")]
    assert declared_suite_result(CONTRACT, spec, START) is None
    assert declared_suite_result(CONTRACT, [*spec, _row(3, "Edit", path="src/a.py")], START).blocking
    patch = {"base": "a" * 40, "patch": "diff --git a/benchmark/SPEC.md b/benchmark/SPEC.md\n+x\n"}
    assert docs_only(patch) and declared_suite_result(CONTRACT, [_row(1, "Bash", command="rm src/a.py")], START,
                                                       change=patch) is None
    assert not docs_only({"base": "a" * 40, "patch": patch["patch"] + "diff --git a/src/a.py b/src/a.py\n+y\n"})
    system = {"command": ".venv/bin/python -m pytest -v tests/system"}
    assert system_tests_result(system, [], START, change=patch) is None
    assert system_tests_result(system, [], START, change=None).blocking


def _out(row, text):
    row.result = {**row.result, "excerpt": text}
    return row


def test_a_full_run_counts_in_any_form_and_a_pipe_is_judged_by_the_summary():
    # Agents run e.g. `python -m pytest -q 2>&1 | tail -60`; if only the verbatim command counted, the check would
    # be advisory and implement would end on single files.
    piped = "timeout 600 python -m pytest -q --ignore=tests/system 2>&1 | tail -40"
    green = [_row(1, "Edit"), _out(_row(2, "Bash", command=piped), "....\n57 passed in 3.1s")]
    assert declared_suite_result(CONTRACT, green, START) is None
    # The pipe hides pytest's exit code: a printed failure is red although the call "succeeded".
    red = [_row(1, "Edit"), _out(_row(2, "Bash", command=piped), "F...\n1 failed, 56 passed in 3.1s")]
    assert "failed in its last full run" in declared_suite_result(CONTRACT, red, START).description
    # Another selection is no full run: a single file, -k, or the system tests left in.
    for subset in (f"{UNIT} tests/test_a.py", f"{UNIT} -k totals", ".venv/bin/python -m pytest -v"):
        rows = [_row(1, "Edit"), _out(_row(2, "Bash", command=subset), "3 passed in 0.2s")]
        assert declared_suite_result(CONTRACT, rows, START).blocking, subset


def test_before_a_pipeline_the_full_suite_includes_the_system_tests():
    contract = {**CONTRACT, "preparation": {"environment": {"test": UNIT, "system_test": "pytest -v tests/system"}}}
    unit_only = [_row(1, "Edit"), _row(2, "Bash", command=UNIT)]
    both = [*unit_only, _row(3, "Bash", command="python -m pytest tests/system -q")]
    keys = ("test", "system_test")
    assert "pytest -v tests/system" in declared_suite_result(contract, unit_only, START, keys=keys).description
    assert declared_suite_result(contract, both, START, keys=keys) is None
