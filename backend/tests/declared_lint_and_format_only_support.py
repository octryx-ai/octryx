"""Shared helpers for the test_declared_lint_and_format_only_* modules."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY as PREPARATION_KEY
from tests.declared_test_run_support import DECLARED, _venv
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased, run_workspace
from tests.test_phase_working_copy import _commit_all

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


def _copy(root: Path, *, lint: str = "lintcheck .") -> dict:
    """A run copy at its base commit with the declared environment (the linter in ``.venv/bin``)."""
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "textkit.py").write_text("def truncate_words(text, count):\n    return text\n")
    (root / "src" / "legacy.py").write_text("LEGACY = '" + "x" * 90 + "'\n")  # a base finding the run never touched
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
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
