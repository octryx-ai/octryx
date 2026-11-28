"""Shared helpers for the test_declared_lint_and_format_only_* modules."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY as PREPARATION_KEY
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased, run_workspace

LINTER = '''#!{python}
"""A declared linter in the copy's environment: flake8's E501 over the copy's Python files."""
import pathlib
import sys

bad = 0
for path in sorted(pathlib.Path(".").rglob("*.py")):
    if ".venv" in path.parts:
        continue
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if len(line) > 79:
            print(f"./{{path}}:{{number}}:80: E501 line too long ({{len(line)}} > 79)")
            bad = 1
sys.exit(bad)
'''


LONG = "    assert truncate_words('one two three four five six seven', 2) == 'one two'  # E501\n"


TEST_FILE = "tests/test_textkit.py"


DECLARED_TEST = "python -m pytest -v tests/ --junitxml=test-reports/report.xml"
DECLARED = {"source": "coding_setup", "path": [".venv/bin"], "test": DECLARED_TEST, "setup": [], "probes": []}


def _venv(root: Path, interpreter: str) -> None:
    shim = root / ".venv" / "bin" / "python"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(f'#!/bin/sh\necho "$0|$PATH|$VIRTUAL_ENV" >> "{root}/.venv/invocations.log"\nexec "{interpreter}" "$@"\n')
    shim.chmod(0o755)


def _commit_all(root) -> None:
    for argv in (["git", "init", "-q"], ["git", "add", "."],
                 ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
        subprocess.run(argv, cwd=root, check=True, capture_output=True)


def _copy(root: Path, *, lint: str = "lintcheck .") -> dict:
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "textkit.py").write_text("def truncate_words(text, count):\n    return text\n")
    (root / "src" / "legacy.py").write_text("LEGACY = '" + "x" * 90 + "'\n")
    _commit_all(root)
    _venv(root, sys.executable)
    linter = root / ".venv" / "bin" / "lintcheck"
    linter.write_text(LINTER.format(python=sys.executable))
    linter.chmod(0o755)
    return {"local_path": str(root), "base_sha": "HEAD",
            PREPARATION_KEY: {"state": "ready", "runtime": "server",
                              "spec": {"environment": {**DECLARED, "lint": lint}}}}


def _gate_definition(gate_checks: list[dict], *, phase_checks: list[dict] | None = None) -> dict:
    work = copy.deepcopy(PHASE)
    if phase_checks is not None:
        work["workflow_contract"]["checks"] = phase_checks
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "implement", "type": "phase", "label": "Implement", "config": work},
                  {"id": "green", "type": "gate", "config": {"phase": "implement", "checks": gate_checks}},
                  {"id": "pushed", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "implement"},
                  {"id": "2", "source_node_id": "implement", "target_node_id": "green"},
                  {"id": "3", "source_node_id": "green", "target_node_id": "pushed", "when": "passed"},
                  {"id": "4", "source_node_id": "green", "target_node_id": "implement", "when": "failed",
                   "kind": "loop", "max_iterations": 2}],
    }


async def _started(db, definition: dict, context: dict | None = None):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=session)
    run.context = {**dict(run.context or {}), **(context or {})}
    await db.commit()
    return admin, session, run


async def _kinds(db, run) -> list[tuple[str, str]]:
    return [(event.kind, event.node_id) for event in (await db.execute(
        select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars()]


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
