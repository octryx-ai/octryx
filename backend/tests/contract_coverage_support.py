"""Shared test-first run, contract copy and submission helpers for the test contract coverage tests."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

from app.models import WorkflowRun
from app.time_utils import utc_now
from app.tools.context import ToolContext
from app.tools.registry import TOOL_REGISTRY
from tests.phased_workflow_fixtures import admin_user
from tests.test_workflow_run_hitl import _item, _start, contract_definition

FILE = "tests/test_textkit.py"


REGRESSION = [f"{FILE}::test_normalize_whitespace_collapses_and_trims", f"{FILE}::test_word_count_counts_words",
              f"{FILE}::test_slugify_lowercases_and_joins_with_hyphens"]


NEW = [f"{FILE}::test_truncate_words_returns_first_words_joined_by_single_spaces",
       f"{FILE}::test_truncate_words_appends_ellipsis_directly_after_last_kept_word",
       f"{FILE}::test_truncate_words_zero_returns_empty_string"]


COMMAND = f"python -m pytest -v {FILE}"


def _test_first_definition() -> dict:
    """The contract definition (clarify → draft → confirm → work) with B's red gate after the work phase."""
    definition = contract_definition()
    definition["nodes"].append({"id": "red", "type": "gate", "label": "Red",
                                "config": {"checks": [{"type": "tests_red", "blocking": True,
                                                       "description": "The new tests fail first"}]}})
    edges = [edge for edge in definition["edges"] if edge["source_node_id"] != "work"]
    edges += [{"id": "w1", "source_node_id": "work", "target_node_id": "red"},
              {"id": "w2", "source_node_id": "red", "target_node_id": "done", "when": "passed"},
              {"id": "w3", "source_node_id": "red", "target_node_id": "work", "when": "failed", "kind": "loop",
               "max_iterations": 2}]
    definition["edges"] = edges
    return definition


def _base_copy(root: Path) -> str:
    """The run's working copy at its base: the existing tests (normalize_whitespace, word_count, slugify) defined."""
    (root / "tests").mkdir(parents=True)
    names = [test.split("::")[-1] for test in REGRESSION]
    (root / FILE).write_text("".join(f"def {name}():\n    assert True\n\n\n" for name in names))
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    for argv in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "base"]):
        subprocess.run(argv, cwd=root, check=True, capture_output=True, env=env)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


async def _clarify(db, tmp_path, *, definition: dict | None = None, dor: list[str] | None = None,
                   with_copy: bool = True):
    item = await _item(db)
    admin = await admin_user(db)
    if dor is not None:  # the item's confirmed Definition of Ready (Workflow A triage, outcome done)
        db.add(WorkflowRun(id=str(uuid.uuid4()), workflow_kind="phased", workflow_key="jira-intake-triage",
                           status="completed", outcome="done", work_item_id=item.id, completed_at=utc_now(),
                           requested_by=admin.id,
                           context={"definition_of_ready": {"type": "feature", "acceptance_criteria": dor,
                                                            "complete": True}}))
        await db.flush()
    admin, run, session = await _start(db, definition or _test_first_definition(), work_item_id=item.id)
    assert run.current_node_id == "clarify"
    if with_copy:
        root = tmp_path / uuid.uuid4().hex[:8]
        base = _base_copy(root)
        run.context = {**dict(run.context or {}), "local_path": str(root), "base_sha": base}
        await db.flush()
    context = ToolContext(user_id=admin.id, project_ids=[], roles=["admin"], session_id=session.id, db=db,
                          project_config={})
    return run, session, context


async def _submit(context, criteria: list[dict]) -> dict:
    return await TOOL_REGISTRY["submit_test_contract"].execute({"criteria": criteria}, context)


def _criterion(ac_id: str, text: str, tests: list[tuple[str, str]]) -> dict:
    return {"id": ac_id, "text": text, "command": COMMAND, "tests": [{"id": test, "role": role} for test, role in tests]}


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
