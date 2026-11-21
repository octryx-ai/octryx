"""Judge-s4c B1, L2, L3, L6, L9, L11 (client). Git only in temporary repositories with local bare remotes."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from octryx_claude import handoff_hooks, session_rules, work_state
from octryx_claude.handoff_resume import run_resume
from octryx_claude.work_state import WorkStateError, capture_work_state, create_branch, may_push, push_branch
from tests.handoff_support import Platform, context, git, hand_over, remote_branches

from .gitrepo import requires_git

pytestmark = requires_git
BRANCH = "octryx-handoff/BRD-1/U-20260101-0000"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = t\n\temail = t@example.test\n[commit]\n\tgpgsign = false\n"
                      "[core]\n\tautocrlf = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    registered, fork = tmp_path / "registered.git", tmp_path / "fork.git"
    for bare in (registered, fork):
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo = tmp_path / "work"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a").write_text("a\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "remote", "add", "origin", str(registered))
    git(repo, "push", "-q", "origin", "main")
    (repo / "a").write_text("changed\n")
    return {"repo": repo, "registered": registered, "fork": fork}


def _capture(repo: Path):
    work = capture_work_state(repo, user_name="U", user_email="u@x", message="WIP")
    create_branch(repo, BRANCH, work.wip_commit)
    return work


# --- B1: the real push targets, no tags, never forced ---------------------------------------------------------------


def test_a_pushurl_to_an_unregistered_fork_never_receives_the_push(setup):
    git(setup["repo"], "config", "remote.origin.pushurl", str(setup["fork"]))
    work = _capture(setup["repo"])
    registered = [str(setup["registered"])]
    assert work.push_urls == [str(setup["fork"])]
    assert not may_push("branch", work.remote_url, registered, work.push_urls)
    assert not push_branch(work, BRANCH, registered) and not push_branch(work, BRANCH)
    assert remote_branches(setup["fork"]) == [] and remote_branches(setup["registered"]) == ["refs/heads/main"]


def test_push_insteadof_is_applied_before_the_check(setup):
    git(setup["repo"], "config", f"url.{setup['fork']}.pushInsteadOf", str(setup["registered"]))
    work = _capture(setup["repo"])
    assert work.push_urls == [str(setup["fork"])]
    assert not push_branch(work, BRANCH, [str(setup["registered"])])
    assert remote_branches(setup["fork"]) == []


def test_the_handoff_falls_back_to_the_bundle_when_the_push_goes_elsewhere(state, setup):
    git(setup["repo"], "config", "remote.origin.pushurl", str(setup["fork"]))
    platform = Platform(repositories=[str(setup["registered"])])
    report = hand_over(state, platform, setup["repo"])
    assert report.ok and not report.items[0].pushed and report.items[0].bundle_id == "bundle-1"
    assert remote_branches(setup["fork"]) == []


def test_follow_tags_never_pushes_a_tag_and_only_the_branch_travels(setup):
    git(setup["repo"], "tag", "-a", "v1", "-m", "annotated")
    git(setup["repo"], "config", "push.followTags", "true")
    work = _capture(setup["repo"])
    git(setup["repo"], "tag", "-a", "v2", "-m", "on the wip", work.wip_commit)
    assert push_branch(work, BRANCH, [str(setup["registered"])])
    assert remote_branches(setup["registered"]) == ["refs/heads/main", f"refs/heads/{BRANCH}"]


def test_a_push_is_never_forced(setup, tmp_path):
    work = _capture(setup["repo"])
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(setup["registered"]), str(other)], check=True)
    (other / "x").write_text("someone else\n")
    git(other, "add", ".")
    git(other, "commit", "-q", "-m", "theirs")
    git(other, "push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}")
    theirs = git(setup["registered"], "rev-parse", f"refs/heads/{BRANCH}")
    assert not push_branch(work, BRANCH, [str(setup["registered"])])  # a non-fast-forward is refused, not forced
    assert git(setup["registered"], "rev-parse", f"refs/heads/{BRANCH}") == theirs
    assert "--force" not in work_state.PUSH_FLAGS and "-f" not in work_state.PUSH_FLAGS


# --- L2: secret paths, case-insensitive and literal -----------------------------------------------------------------


def test_secret_paths_are_left_out_case_insensitively_and_literally(setup):
    repo = setup["repo"]
    names = ["ID_RSA", "server.PEM", "My.Key", ".ENV", "x[1].pem", ":x.env", "kubeconfig", ".pgpass",
             "service-account.json", "secret.gpg", "terraform.tfstate", "conf/credentials.json"]
    for name in names:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("SECRET\n")
    (repo / "x1.txt").write_text("ordinary\n")
    work = capture_work_state(repo, user_name="U", user_email="u@x", message="WIP")
    tree = git(repo, "ls-tree", "-r", "--name-only", work.wip_commit).splitlines()
    assert set(work.excluded_files) == set(names)
    assert not set(names) & set(tree) and "x1.txt" in tree


def test_a_secret_that_slipped_into_the_tree_stops_the_capture(setup, monkeypatch):
    repo = setup["repo"]
    (repo / "id_rsa").write_text("SECRET\n")
    real = work_state.git

    def no_reset(root, *args, **kwargs):
        if args[:1] == ("reset",):
            return ""
        return real(root, *args, **kwargs)

    monkeypatch.setattr(work_state, "git", no_reset)
    with pytest.raises(WorkStateError) as refused:
        capture_work_state(repo, user_name="U", user_email="u@x", message="WIP")
    assert refused.value.code == "secret_path_not_excluded"


# --- L3: no capture mid-merge or mid-rebase -------------------------------------------------------------------------


@pytest.mark.parametrize(("operation", "code"), [("merge", "merge_in_progress"), ("rebase", "rebase_in_progress")])
def test_a_half_done_merge_or_rebase_is_refused(setup, operation, code):
    repo = setup["repo"]
    git(repo, "checkout", "-q", "-b", "other")
    (repo / "a").write_text("other\n")
    git(repo, "commit", "-qam", "other")
    git(repo, "checkout", "-q", "main")
    (repo / "a").write_text("main\n")
    git(repo, "commit", "-qam", "main")
    if operation == "merge":
        subprocess.run(["git", "merge", "other"], cwd=repo, capture_output=True)
    else:
        git(repo, "checkout", "-q", "other")
        subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True)
    with pytest.raises(WorkStateError) as refused:
        capture_work_state(repo, user_name="U", user_email="u@x", message="WIP")
    assert refused.value.code == code


# --- L6: the crossing marker is atomic ------------------------------------------------------------------------------


def test_only_the_first_claim_of_a_crossing_wins(tmp_path):
    assert handoff_hooks.claim_crossing(tmp_path, "2026-10-06T10:00:00Z") is True
    assert handoff_hooks.claim_crossing(tmp_path, "2026-10-06T10:00:00Z") is False
    assert handoff_hooks.claim_crossing(tmp_path, "2026-10-07T10:00:00Z") is True


# --- L9: hint wording, nudges need work:manage ----------------------------------------------------------------------


def test_the_hint_says_what_works_and_what_needs_work_manage(state):
    credentials = state.credentials()
    credentials.pop("scopes", None)
    state.write_credentials(credentials)
    hint = session_rules.scope_notice(state)
    assert "agent board" in hint and "/handoff still work" in hint and "octryx-claude login" in hint


def test_offer_and_update_nudges_need_work_manage(state, monkeypatch, capsys):
    from .test_session_rules import _stop

    credentials = state.credentials()
    credentials.pop("scopes", None)
    state.write_credentials(credentials)
    body = {"state": "passed", "handoff_nudges": [
        {"work_item_key": "BRD-6", "marker": "offer:c1:2026-10-06T10:00:00Z", "kind": "offer"},
        {"work_item_key": "BRD-7", "marker": "c2:-:0", "kind": "update"}]}
    assert _stop(state, monkeypatch, capsys, body) == ""


# --- L11: the resume key is URL-encoded -----------------------------------------------------------------------------


def test_the_resume_key_is_url_encoded(state):
    platform = Platform()
    platform.commits = [{"repo": {}}]  # the fake answers a resume from the last commit
    with platform.client() as http:
        run_resume(state, context(), http, key="BRD 6&x=1/..", cwd=Path("/nonexistent"))
    resume = platform.requests[0]
    assert resume.url.params["key"] == "BRD 6&x=1/.." and list(resume.url.params) == ["key"]


def test_may_push_fails_closed_without_the_push_targets(setup):
    work = _capture(setup["repo"])
    registered = [str(setup["registered"])]
    assert may_push("branch", work.remote_url, registered, work.push_urls)
    assert not may_push("branch", work.remote_url, registered)  # unknown push targets: never
    assert not may_push("branch", work.remote_url, registered, [])


@pytest.mark.parametrize("key", ["BRD..6", "x.lock", "a.lock.lock", "..", "-.lock"])
def test_branch_names_are_always_valid_refs(key):
    branch = work_state.branch_name(key, "u", datetime(2026, 1, 1, 12, 0))
    assert subprocess.run(["git", "check-ref-format", f"refs/heads/{branch}"]).returncode == 0, branch


def test_an_unborn_repository_says_head_missing(tmp_path):
    repo = tmp_path / "unborn"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "f").write_text("x")
    with pytest.raises(WorkStateError) as refused:
        capture_work_state(repo, user_name="U", user_email="u@x", message="WIP")
    assert refused.value.code == "head_missing"
