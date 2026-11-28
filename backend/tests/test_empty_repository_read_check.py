"""A read-only ``tool_called`` check is ``not_applicable`` on a working copy the platform knows holds no file,
so a spec-writing interview on an empty repository can pass."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.services.workflow_checks.library import (
    FAILED,
    NOT_APPLICABLE,
    NOTHING_TO_READ,
    PASSED,
    ToolUse,
    TurnEvidence,
    evaluate_check,
)
from app.services.workflow_runs import safe_git
from app.services.workflow_runs.octryx.stop import run_stop
from app.services.workflow_runs.platform.repo_ref import EMPTY_TREE
from app.services.workflow_runs.workspace.empty_copy import base_is_empty, server_copy_empty
from tests.phased_workflow_fixtures import PHASE
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_support import _bound_run

pytestmark = pytest.mark.usefixtures("scripted_pool")

READ_CHECK = {"type": "tool_called", "params": {"tools": ["read_workspace_file"]}, "blocking": True,
              "description": "The work item, the existing spec and the code were read"}


def test_a_read_only_check_is_not_applicable_only_when_the_platform_knows_there_is_nothing_to_read():
    empty = evaluate_check(READ_CHECK, TurnEvidence(workspace_empty=True))
    assert (empty.outcome, empty.detail) == (NOT_APPLICABLE, NOTHING_TO_READ)
    assert evaluate_check(READ_CHECK, TurnEvidence()).outcome == FAILED
    read = TurnEvidence(tools=[ToolUse("read_workspace_file", True)], workspace_empty=True)
    assert evaluate_check(READ_CHECK, read).outcome == PASSED
    mixed = {**READ_CHECK, "params": {"tools": ["read_workspace_file", "knowledge_search"]}}
    assert evaluate_check(mixed, TurnEvidence(workspace_empty=True)).outcome == FAILED
    tests = {**READ_CHECK, "params": {"tools": ["run_test_suite"]}}
    assert evaluate_check(tests, TurnEvidence(workspace_empty=True)).outcome == FAILED


async def _repository(path: Path, *files: str) -> str:
    path.mkdir()
    assert (await safe_git.git(path, "init", "-q"))[0] == 0
    for name in files:
        (path / name).write_text("x\n")
    await safe_git.git(path, "add", "-A")
    code, _out, err = await safe_git.git(path, "commit", "-q", "--allow-empty", "-m", "init")
    assert code == 0, err
    return (await safe_git.git(path, "rev-parse", "HEAD"))[1].strip()


class _Run:
    def __init__(self, context: dict):
        self.context = context


@pytest.mark.asyncio
async def test_the_base_and_the_server_copy_are_judged_by_git(tmp_path):
    empty = tmp_path / "empty"
    head = await _repository(empty)
    assert await base_is_empty(_Run({"base_sha": head, "local_path": str(empty)}))
    assert await base_is_empty(_Run({"base_sha": EMPTY_TREE}))
    assert not await base_is_empty(_Run({"base_sha": head}))
    assert await server_copy_empty(_Run({"local_path": str(empty)}))
    (empty / "notes.md").write_text("new\n")
    assert not await server_copy_empty(_Run({"local_path": str(empty)}))
    full = tmp_path / "full"
    head = await _repository(full, "README.md")
    assert not await base_is_empty(_Run({"base_sha": head, "local_path": str(full)}))
    assert not await server_copy_empty(_Run({"local_path": str(full)}))


def _interview() -> dict:
    phase = copy.deepcopy(PHASE)
    phase["workflow_contract"]["checks"] = [READ_CHECK]
    phase["tool_policy"]["allowlist"] = ["read_workspace_file", "list_workspace_directory"]
    return {"execution_kind": "phased",
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "interview", "type": "phase", "label": "Spec questions", "config": phase},
                      {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
            "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "interview"},
                      {"id": "2", "source_node_id": "interview", "target_node_id": "done"}]}


async def _stop(db, tmp_path: Path, *files: str, patch: str = "", base_unavailable: bool = False) -> tuple:
    run, gateway, _key, _workspace = await _bound_run(db, _interview())
    copy_path = tmp_path / "server-copy"
    base = await _repository(copy_path, *files)
    run.context = {**dict(run.context or {}), "base_sha": base, "local_path": str(copy_path)}
    await db.flush()
    facts = {"node_id": run.current_node_id, "entry": dict(run.node_state or {}).get("entry"),
             "change": {"base": base, "patch": patch, "truncated": False,
                        **({"base_unavailable": True} if base_unavailable else {})}}
    answer = await run_stop(db, session=gateway, hook_input={"workflow_run_facts": facts}, tool_calls=[],
                            test_prefixes=(("pytest",),))
    return run, answer


@pytest.mark.asyncio
async def test_an_empty_working_copy_lets_the_interview_pass_without_a_read(db, tmp_path):
    run, answer = await _stop(db, tmp_path)
    assert answer["state"] == "passed"
    assert run.current_node_id != "interview"


@pytest.mark.asyncio
async def test_a_repository_with_a_file_still_needs_the_read(db, tmp_path):
    _run, answer = await _stop(db, tmp_path, "README.md")
    assert answer["state"] == "blocked" and "were read" in answer["detail"]


@pytest.mark.asyncio
async def test_a_device_folder_with_new_files_still_needs_the_read(db, tmp_path):
    patch = "diff --git a/notes.md b/notes.md\nnew file mode 100644\n--- /dev/null\n+++ b/notes.md\n@@ -0,0 +1 @@\n+x\n"
    _run, answer = await _stop(db, tmp_path, patch=patch)
    assert answer["state"] == "blocked"


@pytest.mark.asyncio
async def test_a_device_without_the_base_proves_nothing(db, tmp_path):
    _run, answer = await _stop(db, tmp_path, base_unavailable=True)
    assert answer["state"] == "blocked"


@pytest.mark.asyncio
async def test_a_lost_server_copy_is_prepared_again_through_the_prepare_tool(tmp_path, monkeypatch):
    from app.services.workflow_runs.platform import scm
    from app.services.workflow_runs.workspace import empty_copy

    empty = tmp_path / "fresh"
    head = await _repository(empty)
    calls = []

    class _Outcome:
        def __init__(self, ok: bool, result: dict):
            self.ok, self.result = ok, result

    async def prepare(db, run, tool, args, *, capability_class):
        calls.append((tool, args["branch_name"]))
        return _Outcome(True, {"local_path": str(empty)})

    monkeypatch.setattr(scm, "dispatch_tool", prepare)

    class _RunWithRepo(_Run):
        def __init__(self, context: dict, repository: str = "github:octryx-ai/bench", branch: str = "spec/caf-1"):
            super().__init__(context)
            self.repository, self.branch, self.id = repository, branch, "r1"

    gone = {"base_sha": head, "local_path": str(tmp_path / "gone")}
    run = _RunWithRepo(dict(gone))
    assert await empty_copy.base_is_empty(run, db=object())
    assert calls == [("prepare_github_repository", "spec/caf-1")] and run.context["local_path"] == str(empty)
    assert not await empty_copy.base_is_empty(_RunWithRepo(dict(gone)))
    assert not await empty_copy.base_is_empty(_RunWithRepo(dict(gone), repository=""), db=object())

    async def failing(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(scm, "dispatch_tool", failing)
    assert not await empty_copy.base_is_empty(_RunWithRepo(dict(gone)), db=object())


def test_a_question_round_that_asks_nothing_does_not_pass():
    from app.services.workflow_runs.octryx.stop_checks import _questions_missing

    [missing] = _questions_missing("I can't read the run contract. The workflow_run_status tool isn't available.")
    assert (missing.type, missing.outcome, missing.blocking) == ("questions_asked", FAILED, True)
    assert _questions_missing("") and _questions_missing("Defaults I will use\nD1. Euro prices")
    for asked in ("1. Who uses it? Proposed: you alone.", "**1.** Scope? Proposed: beans only",
                  "Questions\n\n 2) Stories? Proposed: S1-S4", "Q3: Look? Proposed: warm"):
        assert _questions_missing(asked) == [], asked


@pytest.mark.asyncio
async def test_the_empty_interview_of_a_question_round_blocks_and_one_with_questions_passes(db, tmp_path):
    definition = _interview()
    definition["nodes"][1]["config"]["workflow_contract"]["workflow_class"] = "spec_interview"
    run, gateway, _key, _workspace = await _bound_run(db, definition)
    copy_path = tmp_path / "server-copy"
    base = await _repository(copy_path)
    run.context = {**dict(run.context or {}), "base_sha": base, "local_path": str(copy_path)}
    await db.flush()
    facts = {"node_id": run.current_node_id, "entry": dict(run.node_state or {}).get("entry"),
             "change": {"base": base, "patch": "", "truncated": False}}

    async def stop(message: str) -> dict:
        return await run_stop(db, session=gateway, tool_calls=[], test_prefixes=(("pytest",),), hook_input={
            "workflow_run_facts": facts, "last_assistant_message": message})

    blocked = await stop("I can't read the run contract.")
    assert blocked["state"] == "blocked" and "numbered questions" in blocked["detail"]
    assert run.current_node_id == "interview"
    passed = await stop("1. Who uses it? Proposed: you alone.\n2. Stories? Proposed: S1 to S4.")
    assert passed["state"] == "passed" and run.current_node_id != "interview"
