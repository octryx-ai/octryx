"""``run_test_suite`` in a server run phase runs the repository's declared test command in the run's copy.

Without this, ``run_test_suite`` would run the API's own ``/usr/local/bin/python -m pytest``
in the copy — "No module named pytest", no test runs — and the phase would report "not called" instead of
pausing ``environment_not_ready``. The repository declares ``path: [.venv/bin]`` and ``python -m pytest -v tests/
--junitxml=test-reports/report.xml``, and ``workspace.prepare`` prepares that ``.venv`` in the copy.

Real path: a phased run's change phase on the server (``run_working_copy`` from the real config assembly), the
registry's ``run_test_suite`` tool, the recorded preparation spec, the turn-end checks guard and the run's pause. The
copy's ``.venv/bin/python`` is a shim to a real interpreter: this test session's (pytest installed), or the same one
without any site-packages (``-I -S``: no pytest on any machine — a runner that cannot start).
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from app.services.workflow_checks.test_command_outcome import ENVIRONMENT, reclassify
from app.services.workflow_checks.test_results import test_run_from_tool as run_from_tool
from app.tools.registry import TOOL_REGISTRY
from tests.declared_test_run_support import (  # noqa: F401
    DECLARED,
    DECLARED_TEST,
    NEW_TEST,
    NO_PYTEST_PYTHON,
    SILENT,
    _checks_turn,
    _phase,
    _server_pipeline,
    _stale_report,
)

# --- the report and the ids are bound to exactly this execution --------------------------------------------------

REGRESSIONS = [f"test_existing_{index}" for index in range(11)]


NEW_FOUR = ["test_truncate_joins_words", "test_truncate_appends_ellipsis", "test_truncate_zero", "test_truncate_negative"]


@pytest.mark.asyncio
async def test_the_declared_command_runs_in_the_copy_with_its_venv_and_reports_canonical_ids(db, tmp_path):
    run, context, working_copy = await _phase(db, tmp_path, interpreter=sys.executable)

    result = await TOOL_REGISTRY["run_test_suite"].execute({"path": "tests/test_truncate.py"}, context)

    assert result["command"] == DECLARED_TEST and result["repo_root"] == str(working_copy)
    assert result["framework"] == "declared" and result["exit_code"] == 1
    assert result["declared_environment"] == {"source": "coding_setup", "path": [".venv/bin"]}
    assert (result["test_report"]["path"], result["test_report"]["fresh"]) == ("test-reports/report.xml", True)
    assert (working_copy / "test-reports" / "report.xml").is_file()  # the JUnit report, in the copy
    # The copy's prepared .venv python ran (explicit PATH and VIRTUAL_ENV), not the API's interpreter.
    started_as, path, virtual_env = (working_copy / ".venv" / "invocations.log").read_text().splitlines()[0].split("|")
    assert started_as == str(working_copy / ".venv" / "bin" / "python")
    assert path.split(":")[0] == str(working_copy / ".venv" / "bin") and virtual_env == str(working_copy / ".venv")
    assert NEW_TEST in result["failed_tests"]
    evidence = run_from_tool("run_test_suite", result, source="chat")
    assert evidence["results"][NEW_TEST]["outcome"] == "failed"
    assert evidence["results"]["tests/test_textkit.py::test_slugify_lowercases"]["outcome"] == "passed"
    _uses, failure = reclassify([SimpleNamespace(name="run_test_suite", succeeded=True, result=result, params={})],
                                [])
    assert failure is None  # the runner ran: a red result, not an environment problem


@pytest.mark.parametrize("case", ["no_venv", "no_pytest", "not_prepared"])
@pytest.mark.asyncio
async def test_a_runner_that_cannot_start_pauses_the_run_environment_not_ready(db, tmp_path, case):
    run, context, _copy = await _phase(
        db, tmp_path, interpreter={"no_venv": None, "no_pytest": NO_PYTEST_PYTHON, "not_prepared": sys.executable}[case],
        state="not_ready" if case == "not_prepared" else "ready")

    result = await TOOL_REGISTRY["run_test_suite"].execute({}, context)

    assert result["exit_code"] != 0 and not result["all_green"]
    assert "/usr/local/bin/python" not in str(result["command"]) and sys.executable not in str(result["command"])
    _uses, failure = reclassify([SimpleNamespace(name="run_test_suite", succeeded=True, result=result, params={})],
                                [])
    assert failure is not None and failure["kind"] == ENVIRONMENT, (case, result)
    loops = dict(run.loop_counters or {})
    await _checks_turn(db, context, [{"tool_name": "run_test_suite", "status": "success", "result": result}])
    assert (run.status, run.pause_reason) == ("paused", "environment_not_ready"), (case, run.status, run.pause_reason)
    # No red, no green, no loop: nothing of this turn is recorded as a test run or a gate result.
    assert not dict(run.context.get("tests") or {}).get("runs") and not dict(run.gate_results or {})
    assert dict(run.loop_counters or {}) == loops


@pytest.mark.asyncio
async def test_a_run_without_a_declared_test_command_and_chat_keep_the_generic_runner(db, tmp_path, monkeypatch):
    import app.tools.runtime_impl._runtime_test_suite_tool as quality_tools

    calls: list[dict] = []

    async def generic(**kwargs):
        calls.append(kwargs)
        return {"exit_code": 0, "all_green": True, "command": "pytest", "repo_root": str(kwargs["cwd"])}

    monkeypatch.setattr(quality_tools, "_resolve_test_suite_service", lambda: generic)
    _run, context, _copy = await _phase(db, tmp_path, interpreter=sys.executable,
                                        environment={**DECLARED, "source": "ci_derived"})
    await TOOL_REGISTRY["run_test_suite"].execute({}, context)
    assert len(calls) == 1  # a CI-derived proposal is no declaration

    chat = SimpleNamespace(**{**vars(context), "project_config": {}})
    await TOOL_REGISTRY["run_test_suite"].execute({}, chat)
    assert len(calls) == 2  # outside a run's copy: unchanged


def test_an_argv_command_that_cannot_start_its_runner_is_an_environment_failure():
    # The generic runner reports its argv: "No module named pytest" from [python, -m, pytest] is environment.
    result = {"command": ["/usr/local/bin/python", "-m", "pytest", ".", "-q"], "exit_code": 1, "stdout": "",
              "stderr": "/usr/local/bin/python: No module named pytest"}
    _uses, failure = reclassify([SimpleNamespace(name="run_test_suite", succeeded=True, result=result, params={})],
                                [])
    assert failure is not None and failure["kind"] == ENVIRONMENT
    assert os.path.basename("/usr/local/bin/python") in failure["command"]


@pytest.mark.asyncio
async def test_four_new_fail_on_assertion_and_eleven_regressions_pass_from_the_fresh_report(db, tmp_path):
    run, context, working_copy = await _phase(db, tmp_path, interpreter=sys.executable)
    (working_copy / "tests" / "test_truncate.py").unlink()
    (working_copy / "tests" / "test_textkit.py").write_text(
        "".join(f"def {name}():\n    assert True\n\n\n" for name in REGRESSIONS)
        + "".join(f"def {name}():\n    assert 'truncate_words' == 'missing'\n\n\n" for name in NEW_FOUR))
    _stale_report(working_copy)  # an earlier run's report: replaced, never read

    result = await TOOL_REGISTRY["run_test_suite"].execute({}, context)

    assert result["test_report"]["fresh"] is True
    evidence = run_from_tool("run_test_suite", result, source="chat")
    outcomes = {test_id: value["outcome"] for test_id, value in evidence["results"].items()}
    assert outcomes == {**{f"tests/test_textkit.py::{name}": "passed" for name in REGRESSIONS},
                        **{f"tests/test_textkit.py::{name}": "failed" for name in NEW_FOUR}}
    for name in NEW_FOUR:  # each fails on its assertion, as the Red gate requires
        assert "assert" in evidence["results"][f"tests/test_textkit.py::{name}"]["message"].lower(), name
    assert "tests/test_truncate.py::test_truncate_words_joins_kept_words" not in outcomes  # the stale report's


@pytest.mark.asyncio
async def test_a_stale_report_and_an_unstartable_runner_are_environment_not_ready_never_red_or_green(db, tmp_path):
    run, context, working_copy = await _phase(db, tmp_path, interpreter=NO_PYTEST_PYTHON)
    stale = _stale_report(working_copy)

    result = await TOOL_REGISTRY["run_test_suite"].execute({}, context)

    assert not stale.exists() and result["test_report"]["fresh"] is False
    assert run_from_tool("run_test_suite", result, source="chat")["results"] == {}
    _uses, failure = reclassify([SimpleNamespace(name="run_test_suite", succeeded=True, result=result, params={})],
                                [])
    assert failure is not None and failure["kind"] == ENVIRONMENT
    await _checks_turn(db, context, [{"tool_name": "run_test_suite", "status": "success", "result": result}])
    assert (run.status, run.pause_reason) == ("paused", "environment_not_ready")
    assert not dict(run.context.get("tests") or {}).get("runs") and not dict(run.gate_results or {})


@pytest.mark.asyncio
async def test_a_stale_report_is_not_trusted_when_the_run_writes_none(db, tmp_path):
    _run, context, working_copy = await _phase(db, tmp_path, interpreter=SILENT)
    stale = _stale_report(working_copy)

    result = await TOOL_REGISTRY["run_test_suite"].execute({}, context)

    assert not stale.exists()
    assert result["test_report"] == {"path": "test-reports/report.xml", "fresh": False}
    assert run_from_tool("run_test_suite", result, source="chat")["results"] == {}  # nothing of the stale report
