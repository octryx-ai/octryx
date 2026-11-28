"""A push to the clone URL moves the tracking ref, a retried push with nothing new counts as pushed and records the commit, and a failed push says why without git's output."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import WorkflowRun
from app.services.workflow_runs.platform import scm, working_copy_git
from app.services.workflow_runs.platform.dispatch import CLASS_PERMISSION, CLASS_TRANSIENT, read_outcome
from tests.phased_workflow_fixtures import admin_user
from tests.workflow_run_succession_support import _git, _origin


async def _url_push_tool(monkeypatch, origin: Path):
    import app.tools.bitbucket_impl._bitbucket_sync_repo as sync_repo

    async def allowed(*_args, **_kwargs):
        return None

    async def no_auth(*_args, **_kwargs):
        return None

    monkeypatch.setattr(sync_repo, "_cloud_push_target", lambda _context, _params: (str(origin), None))
    monkeypatch.setattr(sync_repo, "require_project_repository_operation", allowed)
    monkeypatch.setattr(sync_repo, "bitbucket_write_refusal", allowed)
    monkeypatch.setattr(sync_repo, "_bitbucket_git_auth_env_async", no_auth)
    return sync_repo


@pytest.mark.asyncio
async def test_a_url_push_moves_the_tracking_ref_and_a_retry_reports_the_pushed_head(monkeypatch, tmp_path):
    from app.tools.context import ToolContext

    _seed, work = _origin(tmp_path)
    base = _git(work, "rev-parse", "HEAD")
    sync_repo = await _url_push_tool(monkeypatch, tmp_path / "origin.git")
    context = ToolContext(user_id="u", project_ids=["p"], roles=[], session_id=None, project_config={},
                          workspace_root=str(tmp_path))
    _git(work, "checkout", "-q", "-B", "feature/CHEF-2-x")
    (work / "a.txt").write_text("change\n")
    params = {"project_key": "acme", "repo_slug": "kitchen-helper", "local_path": str(work), "branch_name": "feature/CHEF-2-x",
              "commit_message": "CHEF-2: story"}
    pushed = await sync_repo.CommitAndPushRepositoryBranch().execute(params, context)
    assert pushed["status"] == "pushed", pushed
    assert _git(work, "rev-parse", "refs/remotes/origin/feature/CHEF-2-x") == pushed["head_commit"]

    retry = await sync_repo.CommitAndPushRepositoryBranch().execute(params, context)
    assert (retry["status"], retry["head_commit"]) == ("no_changes", pushed["head_commit"])
    run = WorkflowRun(branch="feature/CHEF-2-x", context={"base_sha": base})
    assert await working_copy_git._already_pushed(str(work), run)


@pytest.mark.asyncio
async def test_a_retried_push_with_nothing_new_counts_as_pushed_and_records_the_commit(db, monkeypatch, tmp_path):
    _seed, work = _origin(tmp_path)
    base = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-q", "-B", "feature/CHEF-2-x")
    (work / "a.txt").write_text("change\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "CHEF-2: story")
    head = _git(work, "rev-parse", "HEAD")  # on Bitbucket, but the tracking ref never moved (a URL push)
    admin = await admin_user(db)
    run = WorkflowRun(title="x", workflow_kind="phased", workflow_key="k", status="running", requested_by=admin.id,
                      repository="bitbucket:acme/kitchen-helper", branch="feature/CHEF-2-x",
                      context={"base_sha": base, "local_path": str(work)})
    db.add(run)
    await db.flush()

    async def dispatch(_db, _run, tool, arguments, *, capability_class):
        return read_outcome({"status": "no_changes", "head_commit": head, "branch_name": "feature/CHEF-2-x"})

    monkeypatch.setattr(scm, "dispatch_tool", dispatch)
    outcome = await scm.push(db, run, {})
    assert outcome.ok and outcome.result["status"] == "already_pushed", outcome.reason
    assert (run.context["head_sha"], run.context["pushed_commits"]) == (head, [head])

    async def nothing(_db, _run, tool, arguments, *, capability_class):
        return read_outcome({"status": "no_changes"})

    monkeypatch.setattr(scm, "dispatch_tool", nothing)
    _git(work, "checkout", "-q", "-B", "feature/CHEF-3-y", base)
    other = WorkflowRun(title="y", workflow_kind="phased", workflow_key="k", status="running", requested_by=admin.id,
                        repository="bitbucket:acme/kitchen-helper", branch="feature/CHEF-3-y",
                        context={"base_sha": base, "local_path": str(work)})
    db.add(other)
    await db.flush()
    assert not (await scm.push(db, other, {})).ok  # the bare base is still "nothing to push"


def test_a_failed_push_says_why_without_git_output():
    from app.tools.bitbucket_impl._bitbucket_sync_repo import _push_failure

    secret = "https://x-token-auth:SECRET@bitbucket.org/acme/kitchen-helper.git"
    cases = {
        f" ! [rejected] main -> main (fetch first)\nerror: failed to push some refs to '{secret}'":
            ("push_rejected_non_fast_forward", "external"),
        f"remote: Invalid username or password.\nfatal: Authentication failed for '{secret}'":
            ("push_auth_failed", CLASS_PERMISSION),
        f"fatal: unable to access '{secret}': Could not resolve host: bitbucket.org": ("push_network", CLASS_TRANSIENT),
        "remote: pre-receive hook declined": ("push_declined_by_hook", "external"),
        "something nobody expected": ("git_push_failed", "external"),
    }
    for stderr, (code, failure_class) in cases.items():
        failure = _push_failure(stderr, 1)
        assert failure["error_code"] == code, stderr
        assert "SECRET" not in str(failure) and "bitbucket.org" not in str(failure)
        assert read_outcome(failure).failure_class == failure_class
    assert _push_failure("", 124)["error_code"] == "push_network"
