"""An item's worktree in later runs: caches stay out, conflicts get the story's work, kept worktrees."""

from __future__ import annotations

from pathlib import Path

from octryx_claude import work_git, work_git_commit
from tests.gitrepo import git, requires_git
from tests.work_git_support import RUN_BRANCH, _main, _op


def _conflicting_items(tmp_path, monkeypatch) -> tuple[Path, str]:
    main, base = _main(tmp_path, monkeypatch)
    work_git.run({"ops": [_op("branch", "a"), _op("branch", "b")]}, main, base=base, run_id="run-1")
    (main / ".octryx-items" / "a" / "app.py").write_text("ROUTES = ['a']\n")
    (main / ".octryx-items" / "b" / "app.py").write_text("ROUTES = ['b']\n")
    (main / ".octryx-items" / "b" / "b.py").write_text("B = 1\n")
    assert work_git.merge(main, "a", f"{RUN_BRANCH}--a")["state"] == "merged"
    assert work_git.merge(main, "b", f"{RUN_BRANCH}--b")["state"] == "conflict"
    return main, base


# --- the device's git work ----------------------------------------------------------------------


@requires_git
def test_test_reports_caches_venvs_and_databases_never_enter_an_items_merge_or_the_change(tmp_path, monkeypatch):
    main, base = _main(tmp_path, monkeypatch)
    work_git.run({"ops": [_op("branch", "api")]}, main, base=base)
    item = main / ".octryx-items" / "api"
    for folder in (item, main):
        (folder / "test-reports" / "screenshots").mkdir(parents=True)
        (folder / "test-reports" / "screenshots" / "home.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
        (folder / "test-reports" / "pipeline-1.xml").write_text("<testsuite/>")
        (folder / ".pytest_cache").mkdir()
        (folder / ".pytest_cache" / "README.md").write_text("cache\n")
        (folder / "kitchen.db").write_bytes(b"SQLite format 3\x00")
        (folder / "src" / "kitchen.egg-info").mkdir(parents=True)  # ``pip install -e .``
        (folder / "src" / "kitchen.egg-info" / "PKG-INFO").write_text("Name: kitchen\n")
        (folder / "src" / "__pycache__").mkdir()
        (folder / "src" / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\x00")
        (folder / "build").mkdir()
        (folder / "build" / "lib.txt").write_text("built\n")
    (item / "search.py").write_text("def search(): ...\n")

    merged = work_git.run({"ops": [_op("merge", "api")]}, main, base=base)

    assert merged["results"][0]["state"] == "merged", merged
    tree = git(main, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    assert "search.py" in tree and not [name for name in tree if name.startswith(("test-reports", ".pytest_cache"))]
    assert "kitchen.db" not in tree
    assert not [name for name in tree if "egg-info" in name or "__pycache__" in name or name.startswith("build/")]
    patch = merged["change"]["patch"]
    assert "search.py" in patch and "test-reports" not in patch and "kitchen.db" not in patch
    excluded = (main / ".git" / "info" / "exclude").read_text().splitlines()
    assert set(work_git_commit.RUNTIME_EXCLUDES) <= set(excluded)


@requires_git
def test_a_conflicted_item_gets_the_storys_work_merged_in_and_resolves_its_markers(tmp_path, monkeypatch):
    main, base = _conflicting_items(tmp_path, monkeypatch)
    item = main / ".octryx-items" / "b"

    retried = work_git.run({"ops": [{**_op("branch", "b"), "sync": True}]}, main, base=base, run_id="run-1")

    result = retried["results"][0]
    assert result["state"] == "branched" and result["kept"] and result["conflicts"] == ["app.py"], result
    assert "<<<<<<<" in (item / "app.py").read_text() and "ROUTES = ['a']" in (item / "app.py").read_text()
    assert (item / "b.py").read_text() == "B = 1\n"  # its own work stands
    again = work_git.branch(main, "b", f"{RUN_BRANCH}--b", run_id="run-1", sync=True)  # a re-sent op changes nothing
    assert again["conflicts"] == ["app.py"] and "<<<<<<<" in (item / "app.py").read_text()

    (item / "app.py").write_text("ROUTES = ['a', 'b']\n")  # the item's agent resolves the conflict
    merged = work_git.merge(main, "b", f"{RUN_BRANCH}--b")

    assert merged["state"] == "merged", merged
    assert (main / "app.py").read_text() == "ROUTES = ['a', 'b']\n" and (main / "b.py").is_file()


@requires_git
def test_a_conflicted_item_whose_worktree_is_gone_gets_it_back_on_its_own_branch(tmp_path, monkeypatch):
    main, base = _conflicting_items(tmp_path, monkeypatch)
    git(main, "worktree", "remove", "--force", str(main / ".octryx-items" / "b"))

    result = work_git.branch(main, "b", f"{RUN_BRANCH}--b", run_id="run-1", sync=True)

    assert result["state"] == "branched" and result["conflicts"] == ["app.py"], result
    assert (main / ".octryx-items" / "b" / "b.py").read_text() == "B = 1\n"  # its commits came back with its branch


@requires_git
def test_an_earlier_runs_worktree_is_never_kept_for_a_new_run(tmp_path, monkeypatch):
    main, base = _main(tmp_path, monkeypatch)
    work_git.branch(main, "api", f"{RUN_BRANCH}--api", run_id="run-1")
    (main / ".octryx-items" / "api" / "old.txt").write_text("the aborted run's work\n")
    assert work_git.branch(main, "api", f"{RUN_BRANCH}--api", run_id="run-1").get("kept")  # same run: kept

    fresh = work_git.branch(main, "api", f"{RUN_BRANCH}--api", run_id="run-2")

    assert fresh["state"] == "branched" and not fresh.get("kept"), fresh
    assert not (main / ".octryx-items" / "api" / "old.txt").exists()
    assert fresh["head"] == git(main, "rev-parse", "HEAD")


@requires_git
def test_a_work_plan_commit_never_deletes_what_a_merged_item_brought_in(tmp_path, monkeypatch):
    main, base = _main(tmp_path, monkeypatch)
    work_git.run({"ops": [_op("branch", "backend")]}, main, base=base)
    (main / ".octryx-items" / "backend" / "server.py").write_text("SERVE = True\n")
    assert work_git.merge(main, "backend", f"{RUN_BRANCH}--backend", base=base)["state"] == "merged"
    (main / "server.py").unlink()  # the merged file vanished from the folder
    (main / "app.py").unlink()  # a file of the base: the coordinator may remove it
    (main / "PLAN.md").write_text("next: system tests\n")  # the coordinator's own edit

    report = work_git.run({"ops": [_op("branch", "system-tests")]}, main, base=base)

    [result] = report["results"]
    assert result["state"] == "branched" and result["kept_files"] == ["server.py"], result
    plan_commit = git(main, "log", "-1", "--format=%H", "--grep=Work plan before item system-tests")
    recorded = sorted(git(main, "show", "--name-status", "--format=", plan_commit).splitlines())
    assert recorded == ["A\tPLAN.md", "D\tapp.py"]  # the coordinator's own edits only
    for folder in (main, main / ".octryx-items" / "system-tests"):
        assert (folder / "server.py").read_text() == "SERVE = True\n"  # in the folder and the new item's worktree
    assert git(main, "status", "--porcelain") == ""


@requires_git
def test_a_kept_item_worktree_gets_the_items_merged_since_it_was_branched(tmp_path, monkeypatch):
    main, base = _main(tmp_path, monkeypatch)
    work_git.run({"ops": [_op("branch", "api"), _op("branch", "tests")]}, main, base=base, run_id="run-1")
    (main / ".octryx-items" / "api" / "server.py").write_text("SERVE = True\n")
    (main / ".octryx-items" / "tests" / "test_server.py").write_text("def test_it(): ...\n")
    assert work_git.merge(main, "api", f"{RUN_BRANCH}--api", base=base)["state"] == "merged"

    again = work_git.branch(main, "tests", f"{RUN_BRANCH}--tests", run_id="run-1", base=base)

    worktree = main / ".octryx-items" / "tests"
    assert again["state"] == "branched" and again["kept"] and not again.get("conflicts"), again
    assert (worktree / "server.py").is_file() and (worktree / "test_server.py").is_file()  # both, nothing lost
    assert git(worktree, "merge-base", "--is-ancestor", git(main, "rev-parse", "HEAD"), "HEAD") == ""


@requires_git
def test_an_item_uses_the_main_folders_prepared_environment_and_never_commits_or_deletes_it(tmp_path, monkeypatch):
    # Without the link every item built its own venv, 8-10 s per item.
    main, base = _main(tmp_path, monkeypatch)
    (main / ".venv" / "bin").mkdir(parents=True)
    (main / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
    contract = {"preparation": {"branch": RUN_BRANCH, "environment": {"path": [".venv/bin"]}}}
    assert work_git.environment_dirs(contract) == [".venv"]
    assert work_git.environment_dirs({"preparation": {"environment": {"path": ["/abs/bin", "../up/bin"]}}}) == []

    started = work_git.run({"ops": [_op("branch", "api")]}, main, base=base, environment=[".venv"])

    item = main / ".octryx-items" / "api"
    assert started["results"][0]["shared_environment"] == [".venv"]
    assert (item / ".venv").is_symlink() and (item / ".venv" / "bin" / "python").is_file()
    (item / "search.py").write_text("def search(): ...\n")
    merged = work_git.run({"ops": [_op("merge", "api")]}, main, base=base)
    assert merged["results"][0]["state"] == "merged", merged
    assert ".venv" not in git(main, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    assert ".venv" not in merged["change"]["patch"]
    assert not item.exists() and (main / ".venv" / "bin" / "python").is_file()  # only the link went


def test_an_item_with_a_linked_environment_tests_its_own_sources_first(tmp_path):
    # An editable install in the shared venv points at the main folder's src.
    from octryx_claude.workspace_prep import own_sources_first

    main = tmp_path / "kitchen"
    item = main / work_git.ITEMS_DIR / "api"
    (main / ".venv").mkdir(parents=True)
    (item / "src").mkdir(parents=True)
    (item / ".venv").symlink_to(main / ".venv")
    environment = {"path": [".venv/bin"]}
    env = {"PYTHONPATH": "/elsewhere"}
    own_sources_first(item, environment, env)
    assert env["PYTHONPATH"].split(":") == [str(item / "src"), "/elsewhere"]
    untouched: dict[str, str] = {}
    own_sources_first(main, environment, untouched)
    assert untouched == {}
