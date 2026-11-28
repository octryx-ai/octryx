"""An environment error in the pipeline pauses instead of fix rounds; a `cd` into the app folder counts for the run;
one `&&` step of a declared lint command runs on its own; the refusal says one command per call."""

from __future__ import annotations

import pytest

from app.services.engineering_knowledge.stacks import built_in
from app.services.workflow_runs import pipeline, pipeline_report
from app.services.workflow_runs.octryx.declared_commands import declared_part, full_suite_run, run_green
from app.services.workflow_runs.pipeline_environment import failure_of
from tests.phase_sessions_models_support import _events
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_pipeline_support import COMMANDS, _at_pipeline

pytestmark = pytest.mark.usefixtures("scripted_pool")

PLAYWRIGHT = ('Traceback (most recent call last):\n  File "system_test/run_system_test.py", line 14, in <module>\n'
              "    from playwright.sync_api import sync_playwright\n"
              "ModuleNotFoundError: No module named 'playwright'\n")
APP = "coffee/flutter/claude"
LINT = "dart format --output=none --set-exit-if-changed . && flutter analyze && dart run tool/check_lines.dart"


def _red(output: str, code: int = 1, command: str = "python3 system_test/run_system_test.py") -> dict:
    return {"command": command, "exit_code": code, "output_tail": output, "failed_tests": []}


def test_a_missing_module_or_command_is_the_environment_a_test_failure_is_not():
    stacks = built_in()
    assert "playwright" in failure_of(_red(PLAYWRIGHT), stacks, None)["reason"]
    assert failure_of(_red("bash: flutter: command not found", 127, "flutter test"), stacks, None) is not None
    assert failure_of(_red("", 127), stacks, None) is not None
    assert failure_of(_red("FAILED tests/test_x.py::test_a\n1 failed, 3 passed in 0.4s"), stacks, None) is None
    assert failure_of({**_red(PLAYWRIGHT), "failed_tests": ["t"]}, stacks, None) is None
    collection = "ERROR collecting tests/test_x.py\nModuleNotFoundError: No module named 'app.newmod'\n"
    assert failure_of(_red(collection), stacks, None) is None


def test_a_missing_module_the_change_touches_is_the_agents():
    broken = "ModuleNotFoundError: No module named 'brewing.ratio'\n"
    assert failure_of(_red(broken), built_in(), {"src", "brewing", "ratio"}) is None
    assert failure_of(_red(broken), built_in(), {"src", "lib"}) is not None


@pytest.mark.asyncio
async def test_the_pipeline_pauses_environment_not_ready_instead_of_a_fix_round(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch)
    report = pipeline.contract_view(run)
    body = {"node_id": report["node_id"], "entry": report["entry"], "results": [
        {"command": COMMANDS[0], "exit_code": 0, "seconds": 3.0, "output_tail": "3 passed in 0.1s", "junit_xml": None},
        {"command": COMMANDS[1], "exit_code": 1, "seconds": 0.1, "output_tail": PLAYWRIGHT, "junit_xml": None}]}
    assert await pipeline_report.record_report(db, run, body, session_id=session.id) == "red"
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "environment_not_ready", "pipeline")
    assert "playwright" in run.context["environment_failure"]["reason"]
    await db.flush()
    assert await _events(db, run, "loop_iteration") == []
    [reported] = await _events(db, run, "pipeline_reported")
    assert "playwright" in reported.detail["environment"]


def test_a_cd_into_the_app_folder_is_the_declared_full_run():
    command = f"cd {APP} && flutter test 2>&1 | tail -5"
    assert full_suite_run(command, "flutter test", APP) and full_suite_run(f"cd {APP}/ && flutter test", "flutter test",
                                                                           APP)
    assert run_green(command, "flutter test", succeeded=True, output="00:12 +40: All tests passed!", app_folder=APP)
    assert not full_suite_run(f"cd {APP}/test && flutter test", "flutter test", APP)
    assert not full_suite_run(command, "flutter test")


def test_one_step_of_the_declared_lint_runs_on_its_own_a_chain_with_semicolon_does_not():
    declared = ("flutter test", LINT)
    assert declared_part("flutter analyze", declared, APP)
    assert declared_part(f"cd {APP} && flutter analyze 2>&1 | tail -5", declared, APP)
    assert not declared_part("flutter analyze --write=x", declared, APP)
    assert not declared_part("flutter test 2>&1 | tail -5; flutter analyze", declared, APP)


def test_the_strict_shell_refusal_names_the_way_and_no_rule_the_parser_does_not_have():
    from app.services.workflow_runs.run_texts import run_text

    text = run_text("shell.strict_refused", phase="Minimal fix")
    assert "one command per call" not in text and "Next:" in text
