from __future__ import annotations

import json
import os
from pathlib import Path

from octryx_claude import workspace_prep
from tests.gitrepo import git, requires_git
from tests.test_device_session_parity import BASE, RUN  # noqa: F401
from tests.workspace_prep_support import BRANCH, _contract, _origin


def _earlier_teamwork_run(folder: Path) -> str:
    from octryx_claude import work_git

    assert workspace_prep.prepare(_contract(), folder, runtime="device")["branch"]["state"] == "checked_out"
    head = git(folder, "rev-parse", "HEAD")
    (folder / "docs").mkdir()
    (folder / "docs" / "CHEF-2.md").write_text("the old plan\n")
    ops = [{"op": "branch", "key": key, "branch": f"{BRANCH}--{key}"} for key in ("core", "web")]
    work_git.run({"ops": ops}, folder, base=head, run_id="run-old")
    (folder / ".octryx-items" / "core" / "core.py").write_text("OLD = 1\n")
    work_git.merge(folder, "core", f"{BRANCH}--core")
    (folder / "wip.txt").write_text("the old run's unfinished edit\n")
    return head


def _new_run(head: str, *, run_commits: bool) -> dict:
    contract = _contract()
    contract["preparation"].update(head=head, run_commits_on_device=run_commits)
    return contract


@requires_git
def test_a_new_runs_first_preparation_cleans_what_an_earlier_run_left_on_the_device(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    head = _earlier_teamwork_run(folder)
    tip = git(folder, "rev-parse", "HEAD")

    # The run's own git work on the device (any later turn of the same run): nothing is touched.
    same = workspace_prep.prepare(_new_run(head, run_commits=True), folder, runtime="device")
    assert "earlier_run_cleaned" not in same and git(folder, "rev-parse", "HEAD") == tip
    assert (folder / ".octryx-items" / "web").is_dir()

    report = workspace_prep.prepare(_new_run(head, run_commits=False), folder, runtime="device")

    assert report["branch"]["state"] == "already", report
    cleaned = report["earlier_run_cleaned"]
    assert cleaned["worktrees"] == ["web"] and cleaned["branches"] == [f"{BRANCH}--core", f"{BRANCH}--web"]
    assert cleaned["reset"] == {"from": tip, "to": head}
    assert git(folder, "rev-parse", "HEAD") == head and not (folder / "core.py").exists()
    assert not (folder / ".octryx-items" / "web").exists() and git(folder, "branch", "--list", f"{BRANCH}--*") == ""
    assert git(folder, "status", "--porcelain") == ""
    # Nothing is lost: the old tip under refs/octryx/leftovers, the uncommitted file in a named stash.
    assert git(folder, "for-each-ref", "--format=%(objectname)", "refs/octryx/leftovers/") == tip
    assert "octryx-leftovers" in git(folder, "stash", "list")


@requires_git
def test_a_persons_own_commit_on_the_run_branch_is_never_reset(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    head = _earlier_teamwork_run(folder)
    (folder / "fix.py").write_text("# the owner's fix\n")
    git(folder, "add", "fix.py")
    git(folder, "commit", "-q", "-m", "a person's commit")
    tip = git(folder, "rev-parse", "HEAD")

    report = workspace_prep.prepare(_new_run(head, run_commits=False), folder, runtime="device")

    assert "reset" not in report.get("earlier_run_cleaned", {}) and git(folder, "rev-parse", "HEAD") == tip


@requires_git
def test_a_leftovers_stash_is_dropped_once_its_work_is_on_the_branch(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    git(folder, "checkout", "-q", "-b", "docs/OCX-19-spec")
    edited = "def slugify(text):\n    return text.lower()  # the spec run's edit\n"
    (folder / "textkit.py").write_text(edited)
    (folder / "SPEC.md").write_text("the spec\n")
    assert workspace_prep.prepare(_contract(), folder, runtime="device")["branch"]["stashed"]
    (folder / "own.txt").write_text("a person's stash\n")
    git(folder, "stash", "push", "-q", "--include-untracked", "-m", "mine")

    # The next story builds on the pushed spec: its branch has the spec run's files.
    (folder / "textkit.py").write_text(edited)
    (folder / "SPEC.md").write_text("the spec\n")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "the pushed spec, as the platform committed it")
    report = workspace_prep.prepare(_contract(), folder, runtime="device")

    assert report["leftovers_dropped"] and report["leftovers_dropped"][0].startswith("octryx-leftovers docs/OCX-19")
    stashes = git(folder, "stash", "list")
    assert "octryx-leftovers" not in stashes and "mine" in stashes  # a person's stash is never touched


@requires_git
def test_test_reports_and_runtime_files_are_excluded_even_without_a_declared_environment(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    workspace_prep.prepare_environment(folder, None)
    (folder / "test-reports" / "screenshots").mkdir(parents=True)
    (folder / "test-reports" / "screenshots" / "a.png").write_bytes(b"\x89PNG")
    (folder / "app.db").write_bytes(b"SQLite")
    assert git(folder, "status", "--porcelain") == ""


def test_the_repository_s_environment_file_prepares_its_app_folder_and_the_agent_s_path(tmp_path):
    pointer = {"source": "environment_file", "environment_file": "web/claude/.octryx/environment.json",
               "app_folder": "web/claude", "setup": [], "path": [], "probes": []}
    assert workspace_prep.prepare_environment(tmp_path, pointer)["environment_file"]["state"] == "missing"
    target = tmp_path / "web/claude/.octryx/environment.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"setup": ["mkdir -p .venv/bin && pwd > .venv/where"], "test": "pytest",
                                  "path": [".venv/bin"]}))
    report = workspace_prep.prepare_environment(tmp_path, pointer)
    app = (tmp_path / "web/claude").resolve()
    assert report["state"] == "environment_file" and report["environment_file"]["state"] == "ok"
    # The file's declared commands go up, so a phase may run them as declared (/73).
    assert report["environment_file"]["commands"] == {"test": "pytest"}
    assert (app / ".venv/where").read_text().strip() == str(app)
    env = {"PATH": "/usr/bin"}
    workspace_prep.child_path({"preparation": {"branch": "b", "environment": pointer}}, str(tmp_path), env)
    assert env["PATH"].split(os.pathsep)[0] == str(app / ".venv/bin")


@requires_git
def test_a_run_taking_its_folder_back_from_another_run_works_on_its_own_branch_and_keeps_the_others_leftovers(
        tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    git(folder, "checkout", "-q", "-b", "bugfix/OCX-112-booklist-page-1")
    (folder / "b_done.py").write_text("# B's committed work\n")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "B's commit")
    (folder / "textkit.py").write_text("# B's uncommitted edit\n")
    (folder / "b_new.py").write_text("# B's new file\n")
    report = workspace_prep.prepare(_contract(), folder, runtime="device")["branch"]
    assert report["state"] == "checked_out" and report["previous"] == "bugfix/OCX-112-booklist-page-1"
    assert git(folder, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert not (folder / "b_done.py").exists() and not (folder / "b_new.py").exists()
    assert "B's uncommitted edit" not in (folder / "textkit.py").read_text()
    assert report["stashed"].startswith("octryx-leftovers bugfix/OCX-112-booklist-page-1")
    stashed = git(folder, "stash", "show", "--include-untracked", "--name-only", "stash@{0}")
    assert "textkit.py" in stashed and "b_new.py" in stashed
    assert git(folder, "rev-parse", "--verify", "bugfix/OCX-112-booklist-page-1")  # B's commit stays on B's branch
