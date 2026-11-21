"""The git work of a ``parallel_work`` node in the device's main folder (teamwork design, WP-B), on real git
repositories:

- ``branch`` commits the coordinator's files, starts the item's worktree inside the folder on its own branch and keeps
  ``/.octryx-items/`` out of the change;
- ``merge`` commits the item's worktree, merges it ``--no-ff`` and removes the worktree;
- a conflict aborts the merge and lists the files, the main folder stays as it was;
- the report carries the main folder's change against the run's base (the review and the push see the whole story);
- a re-run of the same ops is idempotent;
- a device job with ``work_git`` reports it and runs no agent (``work_git_done``).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from octryx_claude import work_git, work_git_commit
from octryx_claude.device_session import WORK_GIT_DONE, SessionRefusedError, prepare_session
from tests.gitrepo import git, requires_git
from tests.test_device_session_parity import BASE, CONTRACT, RUN, _answer, _of, device_state  # noqa: F401
from tests.work_git_support import RUN_BRANCH, _main, _op


def _platform(record: list, contract: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        record.append(request)
        path = request.url.path
        if path.endswith("/client-policy"):
            return httpx.Response(200, json={"state": "allowed"})
        if path.endswith("/sessions/register"):
            return _answer(200, {"state": "registered", "workflow_run_attach": {"state": "attached"},
                                 "workflow_run": contract})
        if path.endswith("/sessions/work-git"):
            return _answer(200, {"state": "recorded", "workflow_run": {**contract, "digest": "d2",
                                                                       "work_git": None}})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@requires_git
def test_branch_starts_a_worktree_inside_the_folder_and_keeps_it_out_of_the_change(tmp_path, monkeypatch):
    main, base = _main(tmp_path, monkeypatch)
    (main / "docs" / "stories").mkdir(parents=True)
    (main / "docs" / "stories" / "CHEF-3.md").write_text("contract: GET /search\n")  # the coordinator's file

    result = work_git.branch(main, "api-search", f"{RUN_BRANCH}--api-search", "AI-Generated-By-octryx: sonnet")

    assert result["state"] == "branched", result
    folder = main / ".octryx-items" / "api-search"
    assert Path(result["folder"]) == folder and (folder / "docs" / "stories" / "CHEF-3.md").is_file()
    assert git(folder, "rev-parse", "--abbrev-ref", "HEAD") == f"{RUN_BRANCH}--api-search"
    # The coordinator's file is committed on the run's branch by the platform identity with the AI trailer.
    assert git(main, "log", "-1", "--format=%an|%B").startswith("Octryx workflow run|Work plan before item")
    assert "AI-Generated-By-octryx: sonnet" in git(main, "log", "-1", "--format=%B")
    assert git(main, "status", "--porcelain") == ""  # the worktrees are excluded, never part of the change
    assert work_git_commit.EXCLUDE in (main / ".git" / "info" / "exclude").read_text()
    assert work_git.is_item_folder(folder) and not work_git.is_item_folder(main)
    assert git(main, "rev-parse", "HEAD") != base


@requires_git
def test_merge_brings_each_item_into_the_main_folder_and_removes_its_worktree(tmp_path, monkeypatch):
    main, base = _main(tmp_path, monkeypatch)
    view = {"node_id": "work", "entry": 2, "seq": 1, "ops": [_op("branch", "api"), _op("branch", "ui")]}
    started = work_git.run(view, main, base=base)
    assert [item["state"] for item in started["results"]] == ["branched", "branched"]
    assert "change" not in started  # nothing merged yet: the run's change stays what it was
    (main / ".octryx-items" / "api" / "search.py").write_text("def search(): ...\n")  # uncommitted item work
    (main / ".octryx-items" / "ui" / "Search.tsx").write_text("export const Search = () => null\n")

    merged = work_git.run({**view, "seq": 2, "ops": [_op("merge", "api"), _op("merge", "ui")]}, main, base=base)

    assert [item["state"] for item in merged["results"]] == ["merged", "merged"], merged
    assert (main / "search.py").is_file() and (main / "Search.tsx").is_file()
    assert not (main / ".octryx-items" / "api").exists() and not (main / ".octryx-items" / "ui").exists()
    assert git(main, "log", "-1", "--format=%s") == "Merge item ui"
    assert len(git(main, "log", "-1", "--format=%P").split()) == 2
    # The report carries the whole story against the run's base: what the review and the push see.
    patch = merged["change"]["patch"]
    assert merged["change"]["base"] == base and "search.py" in patch and "Search.tsx" in patch
    assert (merged["node_id"], merged["entry"], merged["seq"]) == ("work", 2, 2)


@requires_git
def test_a_conflict_aborts_the_merge_and_names_the_files(tmp_path, monkeypatch):
    main, base = _main(tmp_path, monkeypatch)
    work_git.run({"ops": [_op("branch", "a"), _op("branch", "b")]}, main, base=base)
    (main / ".octryx-items" / "a" / "app.py").write_text("ROUTES = ['a']\n")
    (main / ".octryx-items" / "b" / "app.py").write_text("ROUTES = ['b']\n")
    assert work_git.merge(main, "a", f"{RUN_BRANCH}--a")["state"] == "merged"
    head = git(main, "rev-parse", "HEAD")

    result = work_git.merge(main, "b", f"{RUN_BRANCH}--b")

    assert result["state"] == "conflict" and result["files"] == ["app.py"], result
    assert git(main, "rev-parse", "HEAD") == head and git(main, "status", "--porcelain") == ""  # aborted cleanly
    assert (main / ".octryx-items" / "b" / "app.py").read_text() == "ROUTES = ['b']\n"  # the item's work stays


@requires_git
def test_a_rerun_of_the_same_ops_is_idempotent(tmp_path, monkeypatch):
    main, base = _main(tmp_path, monkeypatch)
    first = work_git.branch(main, "api", f"{RUN_BRANCH}--api")
    (main / ".octryx-items" / "api" / "search.py").write_text("x = 1\n")
    again = work_git.branch(main, "api", f"{RUN_BRANCH}--api")
    assert again["state"] == "branched" and again.get("kept") and again["head"] == first["head"]
    assert (main / ".octryx-items" / "api" / "search.py").is_file()  # the item's work is never thrown away

    assert work_git.merge(main, "api", f"{RUN_BRANCH}--api")["state"] == "merged"
    head = git(main, "rev-parse", "HEAD")
    repeated = work_git.merge(main, "api", f"{RUN_BRANCH}--api")
    assert repeated["state"] == "merged" and git(main, "rev-parse", "HEAD") == head  # no second merge commit

    assert work_git.branch(main, "../evil", "x")["state"] == "failed"  # never a path outside .octryx-items


@requires_git
def test_a_device_job_with_work_git_reports_it_and_runs_no_agent(device_state, tmp_path, monkeypatch):  # noqa: F811
    main, base = _main(tmp_path, monkeypatch)
    contract = {**CONTRACT, "phase": None, "facts": {"base_sha": base},
                "work_git": {"node_id": "work", "entry": 3, "seq": 1, "ops": [_op("branch", "api")]}}
    record: list[httpx.Request] = []
    with _platform(record, contract) as http, pytest.raises(SessionRefusedError) as done:
        prepare_session(device_state, base_url=BASE, workspace_id="ws-1", profile="governed", folder=str(main),
                        http=http, shim=Path("/bin/octryx-claude"), workflow_run=RUN, job_id="dj_main")
    assert done.value.code == WORK_GIT_DONE
    report = json.loads(_of(record, "/sessions/work-git")[0].content)
    assert report["results"][0]["state"] == "branched" and (report["node_id"], report["seq"]) == ("work", 1)
    assert (main / ".octryx-items" / "api").is_dir()
    # The registration names the job, so the platform binds the thread's own session (an item's: octryx:<key>).
    assert json.loads(_of(record, "/sessions/register")[0].content)["job_id"] == "dj_main"
