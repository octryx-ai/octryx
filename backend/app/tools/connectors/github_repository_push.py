"""Commit a GitHub working copy and push its branch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import git_commit_identity
from ...services.process_output_redaction import redact_process_output
from ...services.source_control import SourceControlOperation
from ..bitbucket_impl._bitbucket_sync_repo import _push_failure
from ..context import ToolContext
from .cloud_common import _run_subprocess
from .common import _string
from .github import _resolve_github_repo
from .github_source_control import _git_failure
from .github_source_control_common import (
    github_clone_url,
    github_git_auth_env_async,
    github_source_control_metadata,
    require_github_repository_operation,
)


async def _unpushed_commit(repo_path: Path, params: dict) -> bool:
    """HEAD is ahead of its known remote branch (a fast-forward): an earlier attempt committed and did not push."""
    branch = _string(params.get("branch_name"))
    if not branch:
        code, out, _ = await _run_subprocess(["git", "branch", "--show-current"], cwd=str(repo_path))
        branch = out.strip() if code == 0 else ""
    if not branch:
        return False
    code, head, _ = await _run_subprocess(["git", "rev-parse", "HEAD"], cwd=str(repo_path))
    if code != 0:
        return False
    code, remote, _ = await _run_subprocess(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], cwd=str(repo_path)
    )
    if code != 0:
        return False  # no remote branch known here: "no_changes"
    if remote.strip() == head.strip():
        return False
    code, _, git_err = await _run_subprocess(["git", "merge-base", "--is-ancestor", remote.strip(), head.strip()],
                                       cwd=str(repo_path))
    return code == 0  # only a fast-forward: a diverged branch is never pushed over


def _workspace_repo_path(context: ToolContext, local_path: str) -> tuple[Path, dict[str, Any] | None]:
    workspace_root = Path(context.workspace_root or Path.cwd()).resolve()
    repo_path = Path(local_path).expanduser()
    repo_path = repo_path.resolve() if repo_path.is_absolute() else (workspace_root / repo_path).resolve()
    if workspace_root not in repo_path.parents and repo_path != workspace_root:
        return repo_path, {"error": f"local_path must stay inside workspace root: {workspace_root}"}
    if not (repo_path / ".git").exists():
        return repo_path, {"error": "local_path is not a git repository"}
    return repo_path, None


def _no_changes_result(repo_path: Path, *, owner: str, repo: str) -> dict[str, Any]:
    return {
        "status": "no_changes",
        "local_path": str(repo_path),
        "source_control": github_source_control_metadata(
            SourceControlOperation.PUSH,
            owner=owner,
            repo=repo,
            status="no_changes",
            output={"workspace_ref": str(repo_path)},
            evidence={"reason": "git_status_clean"},
        ),
    }


async def _commit_changes(repo_path: Path, commit_message: str, *, push_only: bool) -> dict[str, Any] | None:
    for key, value in git_commit_identity():
        await _run_subprocess(["git", "config", key, value], cwd=str(repo_path))
    for command, error in (
        (["git", "add", "-A"], "git add failed"),
        (["git", "commit", "-m", commit_message], "git commit failed"),
    ) if not push_only else ():
        code, _, git_err = await _run_subprocess(command, cwd=str(repo_path))
        if code != 0:
            return _git_failure(error, code, git_err)
    return None


async def _current_branch(repo_path: Path, params: dict) -> tuple[str, dict[str, Any] | None]:
    branch_name = _string(params.get("branch_name"))
    if not branch_name:
        code, branch_stdout, _ = await _run_subprocess(["git", "branch", "--show-current"], cwd=str(repo_path))
        if code != 0:
            return "", _git_failure("git branch --show-current failed", code)
        branch_name = branch_stdout.strip()
    if not branch_name:
        return "", {"error": "Could not determine current branch name"}
    return branch_name, None


async def _push_branch(
    repo_path: Path, *, clone_url: str, git_env: dict, branch_name: str
) -> tuple[str, dict[str, Any] | None]:
    """Push the branch to the clean origin URL; returns the pushed head commit."""
    await _run_subprocess(["git", "remote", "set-url", "origin", clone_url], cwd=str(repo_path), env=git_env)
    code, _, push_stderr = await _run_subprocess(
        ["git", "push", "--set-upstream", "origin", branch_name],
        cwd=str(repo_path),
        env=git_env,
    )
    if code != 0:
        # The reason class git names (credentials, non-fast-forward, a rule or hook, network), never its output
        # (otherwise only "git push failed" remained and the cause was unknowable).
        return "", _push_failure(push_stderr, code)
    code, head_stdout, _ = await _run_subprocess(["git", "rev-parse", "HEAD"], cwd=str(repo_path))
    if code != 0:
        return "", _git_failure("git rev-parse failed", code)
    return head_stdout.strip(), None


class CommitAndPushGitHubRepositoryBranchTool:
    name = "commit_and_push_github_repository_branch"
    description = "Commit local repository changes and push the current GitHub branch to origin."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        local_path = _string(params.get("local_path"))
        commit_message = _string(params.get("commit_message") or params.get("message"))
        owner, repo = _resolve_github_repo(context, params)
        # push_only: push the branch as it is, never a commit (the platform's fast-forward of an adopted branch).
        push_only = params.get("push_only") is True
        if not local_path or not (commit_message or push_only):
            return {"error": "local_path and commit_message are required"}
        repo_path, invalid = _workspace_repo_path(context, local_path)
        if invalid:
            return invalid
        owner = owner or _string(params.get("owner"))
        repo = repo or _string(params.get("repository") or params.get("repo") or repo_path.name)
        if not owner or not repo:
            return {"error": "repository owner/name is required for GitHub policy checks"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="write")
        if denied:
            return denied
        git_env = await github_git_auth_env_async(context)
        code, stdout, _ = await _run_subprocess(["git", "status", "--porcelain"], cwd=str(repo_path))
        if code != 0:
            return _git_failure("git status failed", code)
        if push_only and stdout.strip():
            return {"error": "push_only: the working copy has uncommitted changes"}
        if not stdout.strip() and not push_only and await _unpushed_commit(repo_path, params):
            # A push that failed after its commit (network, timeout, restart) left the commit unpushed and the copy
            # clean; a retry answering "no_changes" could never succeed. A clean copy whose HEAD is not on its
            # remote branch is pushed as it is.
            push_only = True
        if not stdout.strip() and not push_only:
            return _no_changes_result(repo_path, owner=owner, repo=repo)
        failure = await _commit_changes(repo_path, commit_message, push_only=push_only)
        if failure:
            return failure
        branch_name, failure = await _current_branch(repo_path, params)
        if failure:
            return failure
        clone_url = github_clone_url(context, owner, repo)
        head_commit, failure = await _push_branch(
            repo_path, clone_url=clone_url, git_env=git_env, branch_name=branch_name
        )
        if failure:
            return failure
        return {
            "status": "pushed",
            "local_path": str(repo_path),
            "branch_name": branch_name,
            "commit_message": commit_message,
            "head_commit": head_commit,
            "remote_url": redact_process_output(clone_url),
            "source_control": github_source_control_metadata(
                SourceControlOperation.PUSH,
                owner=owner,
                repo=repo,
                status="pushed",
                output={"workspace_ref": str(repo_path), "branch_name": branch_name, "head_commit": head_commit},
                evidence={"provider_operation": "github_commit_and_push"},
            ),
        }
