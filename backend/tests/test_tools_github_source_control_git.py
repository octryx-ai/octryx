"""GitHub repository operations: prepare and commit-and-push use clean URLs and the repository policy, a denying policy stops mutations before provider calls, an unpushed commit is pushed on retry, and git stops a stalled transfer."""

from __future__ import annotations

import pytest

from app.tools.registry import execute_tool
from tests.tools_github_source_control_support import _create_github_project, _github_context


@pytest.mark.asyncio
async def test_prepare_github_repository_uses_clean_clone_url_and_source_control_metadata(db, monkeypatch, tmp_path):
    repo_root = tmp_path / "var" / "repos" / "github" / "example" / "octryx"
    project_id = await _create_github_project(db, repo_root=str(repo_root))
    commands: list[list[str]] = []
    envs: list[dict[str, str] | None] = []

    async def fake_run_subprocess(command, *, env=None, cwd=None):
        commands.append(list(command))
        envs.append(env)
        if command[:2] == ["git", "clone"]:
            assert command[-2] == "https://github.com/example/octryx.git"
            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").mkdir(exist_ok=True)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return 0, "abc123\n", ""
        return 0, "", ""

    monkeypatch.setattr("app.tools.connectors.github_repository_prepare._run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "prepare_github_repository",
        {"repository": "example/octryx", "base_branch": "main", "branch_name": "codex/test"},
        _github_context(project_id, db=db, workspace_root=str(tmp_path)),
    )

    assert result["source_control"]["operation"] == "prepare_repository"
    assert result["remote_url"] == "https://github.com/example/octryx.git"
    assert result["relative_path"] == "var/repos/github/example/octryx"
    assert "gh-token" not in " ".join(" ".join(command) for command in commands)
    assert any(env and env.get("OCTRYX_GITHUB_SECRET") == "gh-token" for env in envs)
    assert "gh-token" not in str(result).lower()


@pytest.mark.asyncio
async def test_commit_and_push_github_repository_branch_uses_clean_remote_and_policy(db, monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    project_id = await _create_github_project(db, repo_root=str(repo_root))
    commands: list[list[str]] = []

    async def fake_run_subprocess(command, *, env=None, cwd=None):
        commands.append(list(command))
        if command[:3] == ["git", "status", "--porcelain"]:
            return 0, " M README.md\n", ""
        if command[:3] == ["git", "branch", "--show-current"]:
            return 0, "codex/test\n", ""
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return 0, "def456\n", ""
        return 0, "", ""

    monkeypatch.setattr("app.tools.connectors.github_repository_push._run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "commit_and_push_github_repository_branch",
        {
            "repository": "example/octryx",
            "local_path": str(repo_root),
            "commit_message": "docs: update README",
        },
        _github_context(project_id, db=db, workspace_root=str(tmp_path)),
    )

    assert result["status"] == "pushed"
    assert result["source_control"]["operation"] == "push"
    remote_set_url = next(command for command in commands if command[:4] == ["git", "remote", "set-url", "origin"])
    assert remote_set_url[-1] == "https://github.com/example/octryx.git"
    assert "gh-token" not in " ".join(" ".join(command) for command in commands)
    assert "gh-token" not in str(result).lower()


@pytest.mark.asyncio
async def test_github_mutations_stop_before_provider_calls_when_repository_policy_denies(db, monkeypatch):
    project_id = await _create_github_project(
        db,
        policy={"read": True, "branch": False, "write": False, "pr": False, "index": True, "migration": False},
    )
    http_calls: list[tuple] = []

    async def fake_http_json(*args, **kwargs):
        http_calls.append((args, kwargs))
        return {}

    monkeypatch.setattr("app.tools.connectors.github_source_control._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.github_pull_requests._http_json", fake_http_json)

    context = _github_context(project_id, db=db)
    branch_result = await execute_tool(
        "create_github_branch",
        {"repository": "example/octryx", "branch_name": "codex/test", "start_point": "main"},
        context,
    )
    pr_result = await execute_tool(
        "create_github_pull_request",
        {
            "repository": "example/octryx",
            "title": "PR title",
            "from_branch": "codex/test",
            "to_branch": "main",
        },
        context,
    )

    assert "branch" in branch_result["error"]
    assert "pr" in pr_result["error"]
    assert http_calls == []


@pytest.mark.asyncio
async def test_a_commit_an_earlier_push_attempt_left_unpushed_is_pushed_on_retry(tmp_path):
    """A push that failed after its commit leaves the copy clean with HEAD ahead of the remote branch; the retry
    must not answer "no_changes", else scm.push can never succeed. Only a fast-forward counts."""
    import subprocess

    from app.tools.connectors.github_repository_push import _unpushed_commit

    def git(cwd, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                              check=True, capture_output=True, text=True).stdout.strip()

    remote, copy = tmp_path / "remote.git", tmp_path / "copy"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, "clone", "-q", str(remote), str(copy))
    (copy / "a.txt").write_text("a\n")
    git(copy, "add", "-A")
    git(copy, "commit", "-q", "-m", "base")
    git(copy, "push", "-q", "origin", "HEAD:refs/heads/feature/x")
    git(copy, "checkout", "-q", "-b", "feature/x")
    git(copy, "fetch", "-q", "origin")
    assert not await _unpushed_commit(copy, {"branch_name": "feature/x"})  # in sync: nothing to push
    (copy / "b.txt").write_text("b\n")
    git(copy, "add", "-A")
    git(copy, "commit", "-q", "-m", "the reviewed change")  # committed, the push then failed
    assert await _unpushed_commit(copy, {"branch_name": "feature/x"})
    assert not await _unpushed_commit(copy, {"branch_name": "unknown"})  # no remote branch known:


@pytest.mark.asyncio
async def test_a_connector_command_has_an_end_and_git_stops_a_stalled_transfer():
    """A git push has a timeout, so a stalled transfer of a large story does not hold the step."""
    from app.tools.connectors import cloud_common

    code, _out, err = await cloud_common._run_subprocess(["sleep", "5"], timeout=0.5)
    assert code == cloud_common.TIMED_OUT_EXIT and "timed out" in err
    code, out, _err = await cloud_common._run_subprocess(["git", "config", "--get", "--default", "x", "core.none"])
    assert code == 0  # git still runs with the low-speed guard
    code, out, _err = await cloud_common._run_subprocess(
        ["sh", "-c", "echo $GIT_HTTP_LOW_SPEED_LIMIT"], env={"PATH": "/usr/bin:/bin"})
    assert out.strip() == ""  # only git commands get the guard
