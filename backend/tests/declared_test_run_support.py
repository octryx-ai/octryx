"""Shared helpers for the test_declared_test_run_* modules."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.services.workflow_runs.records import active_run_for_session
from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY as PREPARATION_KEY
from tests.test_phase_working_copy import _turn

DECLARED_TEST = "python -m pytest -v tests/ --junitxml=test-reports/report.xml"


DECLARED = {"source": "coding_setup", "path": [".venv/bin"], "test": DECLARED_TEST, "setup": [], "probes": []}


NEW_TEST = "tests/test_truncate.py::test_truncate_words_joins_kept_words"


# The test session's interpreter isolated from every site-packages (``-I -S``): pytest cannot be imported on any
# machine. ``/usr/bin/python3`` was not enough: a user site (``~/Library/Python/3.x``) or a distro package gives it pytest.
NO_PYTEST_PYTHON = "no-pytest"


SILENT = "silent"  # a runner that exits 0 and writes nothing (no output, no report)


def _venv(root: Path, interpreter: str) -> None:
    """The copy's prepared ``.venv/bin/python``: a shim that logs how it was started, then runs ``interpreter``."""
    shim = root / ".venv" / "bin" / "python"
    shim.parent.mkdir(parents=True, exist_ok=True)
    if interpreter == SILENT:
        run = "exit 0"
    elif interpreter == NO_PYTEST_PYTHON:
        run = f'exec "{sys.executable}" -I -S "$@"'
    else:
        run = f'exec "{interpreter}" "$@"'
    shim.write_text(f'#!/bin/sh\necho "$0|$PATH|$VIRTUAL_ENV" >> "{root}/.venv/invocations.log"\n{run}\n')
    shim.chmod(0o755)


STALE_REPORT = ('<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1">'
                '<testcase classname="tests.test_truncate" name="test_truncate_words_joins_kept_words"/>'
                '</testsuite></testsuites>')


def _stale_report(root: Path) -> Path:
    """An earlier run's report in the copy: it says the new test passed."""
    report = root / "test-reports" / "report.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(STALE_REPORT)
    return report


async def _phase(db, tmp_path, *, interpreter: str | None, environment: dict | None = DECLARED,
                 state: str = "ready"):
    config, context, working_copy, _session_root, _resolution = await _turn(db, tmp_path, capability_class="change")
    run = await active_run_for_session(db, context.session_id)
    (working_copy / "tests" / "test_truncate.py").write_text(
        "def test_truncate_words_joins_kept_words():\n    assert 'a b c'.split()[:2] == ['a', 'b', 'c']\n")
    if interpreter:
        _venv(working_copy, interpreter)
    if environment is not None:
        run.context = {**run.context, PREPARATION_KEY: {"state": state, "runtime": "server",
                                                        "spec": {"environment": environment}}}
    await db.flush()
    return run, context, working_copy


async def _checks_turn(db, context, history: list[dict]):
    """The turn's end: the real checks guard reports to the run (``record_phase_turn``)."""
    from app.agent.loops.response._loop_workflow_checks import handle_workflow_checks_guard
    from app.models import Session
    from app.services.prompt_catalog import prompt_set_scope, seed_prompt_set
    from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
    from app.services.workflow_runs.binding import run_turn_resolution

    resolution = await run_turn_resolution(db, await db.get(Session, context.session_id), user_message="Work.")

    async def persist_turn_trace(**_kwargs):
        return None

    with prompt_set_scope(seed_prompt_set()):
        return await handle_workflow_checks_guard(
            db=db, session_id=context.session_id, runtime={"provider_name": "test"}, response={"usage": {}},
            request_messages=[], messages=[], context_snapshot={}, runtime_attempts=[], runtime_settings={},
            usage_model="m", content="Done.", tool_calls=None, has_followup_steps=False, sub_agent_depth=0,
            request_analysis={ROUTING_RESOLUTION_KEY: resolution}, turn_tool_history=history,
            persist_turn_trace=persist_turn_trace)


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
