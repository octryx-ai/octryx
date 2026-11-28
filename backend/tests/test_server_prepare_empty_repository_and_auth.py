"""Server prepare: fetches carry the Bitbucket Git auth, and an empty repository is prepared."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.workflow_runs.platform.dispatch as dispatch_module
import app.services.workflow_runs.workspace.server_prepare as server_prepare
from app.services.git_http_auth import bearer_header_env
from app.services.workflow_runs import safe_git
from app.services.workflow_runs.platform import pr_reviewers, repo_ref, scm
from app.services.workflow_runs.platform.dispatch import FAILED, SUCCEEDED, ToolOutcome
from app.services.workflow_runs.workspace.origin_auth import origin_git_env
from app.services.workflow_runs.workspace.preparation import decide
from app.tools.bitbucket_impl import _bitbucket_sync_repo as sync_repo
from app.tools.context import ToolContext
from tests.policy_engine_support import bearer
from tests.services.knowledge.sources.test_repository_git_token import (  # noqa: F401 - the ``world`` fixture
    BASE,
    CLONE_URL,
    TOKEN,
    _body,
    _setup,
    _url,
    world,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
SECRET_TOKEN = "pat-never-in-argv-0001"  # gitleaks:allow


def _git(*args: str, cwd: Path | str | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def git_identity(tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = t\n\temail = t@example.test\n[commit]\n\tgpgsign = false\n"
                      "[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))


def _recording(monkeypatch) -> list[tuple[tuple[str, ...], dict | None]]:
    calls: list[tuple[tuple[str, ...], dict | None]] = []

    async def recorded(cwd, *args, stdin=None, env=None):
        calls.append((args, dict(env) if env is not None else None))
        return await safe_git.git(cwd, *args, stdin=stdin, env=env)

    monkeypatch.setattr(server_prepare, "git", recorded)
    return calls


def _filled_remote(tmp_path: Path, branches: tuple[str, ...] = ("main",)) -> Path:
    remote, work = tmp_path / "remote.git", tmp_path / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(remote))
    _git("clone", "-q", str(remote), str(work))
    (work / "app.py").write_text("v1\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "base", cwd=work)
    for branch in branches:
        _git("push", "-q", "origin", f"HEAD:{branch}", cwd=work)
    return remote


async def test_every_fetch_from_origin_carries_the_git_env_and_no_credential_in_argv(tmp_path, monkeypatch,
                                                                                   git_identity) -> None:
    remote = _filled_remote(tmp_path, ("main", "feature/ACME-1-x"))
    server = tmp_path / "server"
    _git("clone", "-q", str(remote), str(server))
    calls = _recording(monkeypatch)
    env = bearer_header_env("https://bitbucket.example.test/scm/acme/demo-shop.git", SECRET_TOKEN)

    report = await server_prepare.prepare_locally(server, {"branch": "feature/ACME-1-x", "run_id": "run-1"},
                                                  git_env=env)

    assert report["branch"]["state"] == "checked_out" and report["wip"]["state"] == "absent"
    fetches = [(args, seen) for args, seen in calls if "fetch" in args]
    assert len(fetches) == 2, "the branch and the run's work in progress"
    for _args, seen in fetches:
        assert seen is not None and seen["GIT_CONFIG_COUNT"] == env["GIT_CONFIG_COUNT"]
        headers = {seen[f"GIT_CONFIG_KEY_{i}"]: seen[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(seen["GIT_CONFIG_COUNT"]))}
        assert headers["http.https://bitbucket.example.test/.extraHeader"] == f"Authorization: Bearer {SECRET_TOKEN}"
    assert all(SECRET_TOKEN not in " ".join(args) for args, _ in calls)
    assert all(seen is None for args, seen in calls if "fetch" not in args and "ls-remote" not in args), (
        "local commands get no credential")


async def test_an_empty_repository_is_prepared_on_the_runs_unborn_branch(tmp_path, monkeypatch, git_identity) -> None:
    remote, server = tmp_path / "empty.git", tmp_path / "server"
    _git("init", "-q", "--bare", "-b", "main", str(remote))
    _git("clone", "-q", str(remote), str(server))
    calls = _recording(monkeypatch)
    env = bearer_header_env("https://bitbucket.example.test/scm/acme/demo-shop.git", SECRET_TOKEN)

    report = await server_prepare.prepare_locally(server, {"branch": "feature/ACME-1-first", "run_id": "run-1"},
                                                  git_env=env)

    branch = report["branch"]
    assert (branch["state"], branch["head"]) == ("empty_repository", "")
    assert "no commits yet" in branch["detail"]
    assert decide(report).state == SUCCEEDED, "an empty repository is prepared, not a failure"
    assert _git("symbolic-ref", "HEAD", cwd=server) == "refs/heads/feature/ACME-1-first"
    [(_, ls_remote_env)] = [(args, seen) for args, seen in calls if "ls-remote" in args]
    assert ls_remote_env is not None and SECRET_TOKEN in json.dumps(ls_remote_env), "ls-remote carries the auth"
    (server / "README.md").write_text("first\n")
    _git("add", "-A", cwd=server)
    _git("commit", "-q", "-m", "first", cwd=server)
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=server) == "feature/ACME-1-first"
    assert (await server_prepare.prepare_branch(server, "feature/ACME-1-first"))["state"] == "already"


async def test_an_unborn_folder_whose_origin_has_refs_is_prepared_as_before(tmp_path, git_identity) -> None:
    remote = _filled_remote(tmp_path, ("main", "feature/ACME-2"))
    server = tmp_path / "server"
    _git("init", "-q", "-b", "main", str(server))
    _git("remote", "add", "origin", str(remote), cwd=server)

    branch = await server_prepare.prepare_branch(server, "feature/ACME-2")
    assert branch["state"] == "checked_out" and len(branch["head"]) == 40

    missing = tmp_path / "missing"
    _git("init", "-q", "-b", "main", str(missing))
    _git("remote", "add", "origin", str(tmp_path / "nowhere.git"), cwd=missing)
    refused = await server_prepare.prepare_branch(missing, "feature/ACME-2")
    assert refused["state"] == "unavailable" and "origin could not be read" in refused["detail"]


async def test_origin_git_env_is_the_bitbucket_tools_environment_with_the_repository_token(
    client, db, world, tmp_path, monkeypatch  # noqa: F811 - ``world`` is the imported fixture
) -> None:
    workspace_id, user_id, connection_id = await _setup(db)
    saved = await client.put(_url(workspace_id), headers=bearer(user_id), json=_body(connection_id, git_token=TOKEN))
    assert saved.status_code == 200, saved.text
    config = {"bitbucket_url": BASE, "bitbucket_auth_mode": "bearer_pat",
              "bitbucket_token": "pat-0123456789",  # gitleaks:allow
              "project_id": workspace_id}

    async def fake_context(db_, run_, capability_class, *, workspace_root=None):
        return ToolContext(user_id=user_id, project_ids=[workspace_id], roles=[], session_id="s1",
                           project_config=config, db=db, workspace_root=workspace_root)

    monkeypatch.setattr(dispatch_module, "tool_context", fake_context)
    root = tmp_path / "copy"
    _git("init", "-q", str(root))
    _git("remote", "add", "origin", CLONE_URL, cwd=root)
    run = SimpleNamespace(id="run-1", repository="bitbucket:SHOP/aws-shop-deployment",
                          project_id=workspace_id, requested_by=user_id)

    env = await origin_git_env(db, run, root)
    assert env is not None
    headers = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))}
    assert headers["http.https://bitbucket.example.test/.extraHeader"] == f"Authorization: Bearer {TOKEN}"

    _git("remote", "set-url", "origin", "https://elsewhere.example.test/scm/x/y.git", cwd=root)
    assert await origin_git_env(db, run, root) is None, "a remote on another host gets no credential"
    github = SimpleNamespace(**{**vars(run), "repository": "github:acme/demo-shop"})
    assert await origin_git_env(db, github, root) is None


async def test_the_prepare_tool_clones_an_empty_repository_onto_the_unborn_work_branch(tmp_path, monkeypatch,
                                                                                      git_identity) -> None:
    remote = tmp_path / "empty.git"
    _git("init", "-q", "--bare", "-b", "main", str(remote))
    clone_url = "https://bitbucket.example/scm/PROJ/service-api.git"
    seen: list[list[str]] = []

    async def local_git(command, *, cwd=None, timeout_sec=90, env=None):
        seen.append(list(command))
        local = [str(remote) if item == clone_url else item for item in command]
        process = subprocess.run(local, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)
        return process.returncode, process.stdout, process.stderr

    async def no_policy(*_args, **_kwargs):
        return None

    async def master(*_args):
        return "master"

    monkeypatch.setattr(sync_repo, "_run_git", local_git)
    monkeypatch.setattr(sync_repo, "require_project_repository_operation", no_policy)
    monkeypatch.setattr(sync_repo, "_detect_default_branch", master)
    context = ToolContext(user_id="u1", project_ids=[], roles=[], session_id="s1", workspace_root=str(tmp_path),
                          project_config={"bitbucket_url": "https://bitbucket.example", "bitbucket_auth_mode": "bearer_pat",
                                          "bitbucket_token": "token", "bitbucket_allowed_repos": ["PROJ/service-api"]})

    result = await sync_repo.PrepareBitbucketRepository().execute(
        {"project_key": "PROJ", "repo_slug": "service-api", "branch_name": "feature/PROJ-1-first"}, context)

    assert "error" not in result, result
    assert (result["repository_empty"], result["base_branch"], result["head_commit"]) == (True, "", "")
    local = Path(result["local_path"])
    assert _git("symbolic-ref", "HEAD", cwd=local) == "refs/heads/feature/PROJ-1-first"
    assert ["git", "ls-remote", clone_url] in seen
    again = await sync_repo.PrepareBitbucketRepository().execute(
        {"project_key": "PROJ", "repo_slug": "service-api", "branch_name": "feature/PROJ-1-first"}, context)
    assert again.get("repository_empty") is True, again


async def test_a_run_goes_on_on_an_empty_repository_and_its_refused_pr_says_why(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_dispatch(db, run, tool, arguments, *, capability_class, workspace_root=None):
        calls.append(tool)
        if tool == "create_bitbucket_branch":
            return ToolOutcome(FAILED, {}, "No default branch is defined")
        if tool == "prepare_bitbucket_repository":
            return ToolOutcome(SUCCEEDED, {"local_path": "/nonexistent/copy", "base_branch": "", "head_commit": "",
                                           "repository_empty": True})
        return ToolOutcome(FAILED, {}, "Repository has no default branch")

    async def no_reviewers(*_args):
        return pr_reviewers.PrReviewers(None, (), "bitbucket", "")

    async def named(*_args):
        return "feature/PROJ-1-first"

    async def no_earlier(*_args):
        return None

    async def no_links(*_args):
        return ""

    monkeypatch.setattr(scm, "dispatch_tool", fake_dispatch)
    monkeypatch.setattr(scm, "run_links", no_links)
    monkeypatch.setattr(scm, "reviewers_for", no_reviewers)
    monkeypatch.setattr(scm, "branch_name", named)
    monkeypatch.setattr("app.services.workflow_runs.platform.pr_adoption.earlier_pull_request", no_earlier)
    run = SimpleNamespace(id="run-1", repository="bitbucket:PROJ/service-api", ticket_key="PROJ-1", branch=None,
                          context={}, work_item_id=None, title="First", pull_request=None, project_id="w1")

    created = await scm.create_branch(None, run, {"branch_type": "feature"})
    assert created.ok and run.branch and run.context["repository_empty"] is True
    assert run.context["base_sha"] == repo_ref.EMPTY_TREE and run.context["local_path"] == "/nonexistent/copy"
    assert calls == ["create_bitbucket_branch", "prepare_bitbucket_repository"]

    refused = await scm.open_pr(None, run, {})
    assert refused.state == FAILED and refused.failure_class == "not_configured"
    assert "no commits when the run started" in refused.reason and "default branch" in refused.reason
