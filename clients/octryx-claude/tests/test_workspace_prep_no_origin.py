"""Preparing a folder without origin access: the run's branch, foreign folders, excludes and named stashes."""

from __future__ import annotations

import json

from octryx_claude import workspace_env, workspace_prep
from tests.gitrepo import git, requires_git
from tests.test_device_session_parity import BASE, RUN  # noqa: F401
from tests.workspace_prep_support import BRANCH, _contract, _no_origin_access, _origin


@requires_git
def test_without_origin_access_the_branch_starts_at_the_platforms_commit_when_the_folder_has_it(tmp_path,
                                                                                                monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    head = _no_origin_access(folder, tmp_path)
    contract = _contract()
    contract["preparation"]["head"] = head
    report = workspace_prep.prepare(contract, folder, runtime="device")
    assert report["branch"]["state"] == "checked_out", report
    assert git(folder, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH and git(folder, "rev-parse", "HEAD") == head

    (tmp_path / "second").mkdir()
    other = _origin(tmp_path / "second", monkeypatch)
    _no_origin_access(other, tmp_path)
    missing = _contract()
    missing["preparation"]["head"] = "f" * 40
    refused = workspace_prep.prepare(missing, other, runtime="device")["branch"]
    assert refused["state"] == "unavailable" and "read access to origin" in refused["detail"]
    assert "does not have the branch's commit ffffffffffff" in refused["detail"]
    assert git(other, "rev-parse", "--abbrev-ref", "HEAD") == "main"


@requires_git
def test_a_folder_of_another_repository_is_refused_before_anything_changes(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    git(folder, "remote", "set-url", "origin", "https://someone:s3cr3t@bitbucket.org/demo-team/other.git")
    contract = _contract()
    contract["preparation"]["repository"] = {"provider": "bitbucket", "hosts": ["bitbucket.org"],
                                             "path": "demo-team/test"}
    report = workspace_prep.prepare(contract, folder, runtime="device")
    assert report["branch"]["state"] == "foreign" and "demo-team/test" in report["branch"]["detail"]
    assert report["remote_url"] == "https://bitbucket.org/demo-team/other.git"  # never the user info
    assert "s3cr3t" not in json.dumps(report) and git(folder, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    git(folder, "remote", "set-url", "origin", "git@bitbucket.org:Demo-Team/test.git")
    assert workspace_prep.repository_refusal(folder, contract["preparation"]["repository"]) == ""
    git(folder, "remote", "set-url", "origin", "ssh://git@stash.example:7999/scm/demo-team/test.git")
    server = {"hosts": ["stash.example"], "path": "demo-team/test"}
    assert workspace_prep.repository_refusal(folder, server) == ""


@requires_git
def test_the_server_s_exclude_patterns_keep_the_environment_and_the_test_report_out_of_the_change(tmp_path,
                                                                                                    monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    workspace_env.exclude_environment(folder, [".venv/bin"], ["/.venv/", "/test-reports/", "/../x", "/a/b", "x"])
    excluded = (folder / ".git" / "info" / "exclude").read_text().splitlines()
    assert excluded[-2:] == ["/.venv/", "/test-reports/"]  # only top-level names of the folder
    (folder / "test-reports").mkdir()
    (folder / "test-reports" / "report.xml").write_text("<testsuite/>")
    assert git(folder, "status", "--porcelain").strip() == ""  # the report never becomes part of the change
    workspace_env.exclude_environment(folder, [".tools"])  # an older contract without patterns: the path only
    assert (folder / ".git" / "info" / "exclude").read_text().splitlines()[-1] == "/.tools/"


# --- : a second run on the same Work item found the first run's local branch at the old base ----------


@requires_git
def test_a_local_branch_behind_the_platforms_commit_is_fast_forwarded_without_origin_access(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    old = git(folder, "rev-parse", "HEAD")
    git(folder, "branch", BRANCH, old)  # left over from an earlier run, at the old base
    (folder / "system.py").write_text("# new on main\n")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "main moved on")
    head = _no_origin_access(folder, tmp_path)
    contract = _contract()
    contract["preparation"]["head"] = head
    report = workspace_prep.prepare(contract, folder, runtime="device")
    assert report["branch"]["state"] == "checked_out", report
    assert git(folder, "rev-parse", "HEAD") == head  # not the stale old base

    again = workspace_prep.prepare(contract, folder, runtime="device")  # already on it: still at the commit
    assert again["branch"]["state"] == "already" and git(folder, "rev-parse", "HEAD") == head


@requires_git
def test_a_local_branch_that_diverged_from_the_runs_branch_is_reported_not_used(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    git(folder, "checkout", "-q", "-b", BRANCH)
    (folder / "stale.py").write_text("# an earlier run's work\n")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "earlier run")
    git(folder, "checkout", "-q", "main")
    (folder / "system.py").write_text("# new on main\n")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "main moved on")
    head = _no_origin_access(folder, tmp_path)
    contract = _contract()
    contract["preparation"]["head"] = head
    refused = workspace_prep.prepare(contract, folder, runtime="device")["branch"]
    assert refused["state"] == "unavailable" and "left over from an earlier run" in refused["detail"], refused


@requires_git
def test_leftovers_of_an_earlier_runs_branch_are_set_aside_in_a_named_stash(tmp_path, monkeypatch):
    """A run that left SPEC.md modified on its branch (the platform pushed the change from its server copy) must not
    keep the next story of the epic from starting. On a branch the platform named for a
    run the leftovers go into a named stash (nothing lost); on a person's own branch nothing changes."""
    folder = _origin(tmp_path, monkeypatch)
    git(folder, "checkout", "-q", "-b", "docs/OCX-19-benchmark-web-v1-spec-run-4")
    (folder / "textkit.py").write_text("def slugify(text):\n    return text.lower()  # the spec run's edit\n")
    report = workspace_prep.prepare(_contract(), folder, runtime="device")
    assert report["branch"]["state"] == "checked_out"
    assert report["branch"]["stashed"].startswith("octryx-leftovers docs/OCX-19-benchmark-web-v1-spec-run-4")
    assert "octryx-leftovers" in git(folder, "stash", "list")
    assert git(folder, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH


@requires_git
def test_new_files_left_by_an_earlier_run_are_stashed_too(tmp_path, monkeypatch):
    """New files an earlier run left untracked in the folder are stashed, so they do not block the checkout."""
    folder = _origin(tmp_path, monkeypatch)
    git(folder, "checkout", "-q", "-b", "feature/OCX-21-s2")
    (folder / "NOTES.md").write_text("the earlier run's new file\n")  # the run's branch has NOTES.md as well
    report = workspace_prep.prepare(_contract(), folder, runtime="device")
    assert report["branch"]["state"] == "checked_out" and report["branch"]["stashed"]
    assert (folder / "NOTES.md").read_text() == "branch work\n"
