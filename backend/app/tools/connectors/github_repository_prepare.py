"""Prepare the platform's GitHub cache clone on a work branch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...services.process_output_redaction import redact_process_output
from ...services.source_control import SourceControlOperation
from ..context import ToolContext
from .cloud_common import _run_subprocess
from .common import _string
from .github import _resolve_github_repo
from .github_source_control import _git_failure, _github_default_branch
from .github_source_control_common import (
    github_clone_url,
    github_git_auth_env_async,
    github_source_control_metadata,
    require_github_repository_operation,
)
from .scm_cache_clone import base_sync, cache_clone_lock


def _github_managed_repo_path(context: ToolContext, owner: str, repo: str) -> Path:
    workspace_root = Path(context.workspace_root or Path.cwd()).resolve()
    managed_root = Path(_string(context.project_config.get("managed_repo_root")) or "var/repos/github")
    if not managed_root.is_absolute():
        managed_root = workspace_root / managed_root
    repo_path = (managed_root / owner / repo).resolve()
    if workspace_root not in repo_path.parents and repo_path != workspace_root:
        raise ValueError(f"managed GitHub repository path must stay inside workspace root: {workspace_root}")
    return repo_path


async def _clone_or_set_origin(
    repo_path: Path, *, clone_url: str, git_env: dict, base_branch: str
) -> tuple[bool, dict[str, Any] | None]:
    if not (repo_path / ".git").exists():
        code, _, git_err = await _run_subprocess(
            ["git", "clone", "--branch", base_branch, clone_url, str(repo_path)],
            env=git_env,
        )
        if code != 0:
            return False, _git_failure("git clone failed", code, git_err)
        return True, None
    code, _, git_err = await _run_subprocess(
        ["git", "remote", "set-url", "origin", clone_url],
        cwd=str(repo_path),
        env=git_env,
    )
    if code != 0:
        return False, _git_failure("git remote set-url failed", code, git_err)
    return False, None


async def _checkout_work_branch(
    repo_path: Path, *, git_env: dict, base_branch: str, branch_name: str
) -> tuple[str, dict[str, Any] | None]:
    for command, error in (
        (["git", "fetch", "--prune", "origin"], "git fetch failed"),
        *base_sync(base_branch),
        (["git", "checkout", "-B", branch_name], "git checkout branch failed"),
    ):
        code, _, git_err = await _run_subprocess(command, cwd=str(repo_path), env=git_env)
        if code != 0:
            return "", _git_failure(error, code, git_err)
    code, head_stdout, _ = await _run_subprocess(["git", "rev-parse", "HEAD"], cwd=str(repo_path))
    if code != 0:
        return "", _git_failure("git rev-parse failed", code)
    return head_stdout.strip(), None


def _prepared_result(
    context: ToolContext,
    *,
    owner: str,
    repo: str,
    repo_path: Path,
    base_branch: str,
    branch_name: str,
    cloned: bool,
    clone_url: str,
    head_commit: str,
) -> dict[str, Any]:
    workspace_root = Path(context.workspace_root or Path.cwd()).resolve()
    relative_path = repo_path.relative_to(workspace_root)
    return {
        "repository": f"{owner}/{repo}",
        "local_path": str(repo_path),
        "relative_path": str(relative_path),
        "base_branch": base_branch,
        "branch_name": branch_name,
        "cloned": cloned,
        "remote_url": redact_process_output(clone_url),
        "head_commit": head_commit,
        "source_control": github_source_control_metadata(
            SourceControlOperation.PREPARE_REPOSITORY,
            owner=owner,
            repo=repo,
            status="prepared",
            output={
                "workspace_ref": str(relative_path),
                "head_commit": head_commit,
                "branch_name": branch_name,
                "base_branch": base_branch,
            },
            evidence={"cloned": cloned, "remote_url": redact_process_output(clone_url)},
        ),
    }


class PrepareGitHubRepositoryTool:
    name = "prepare_github_repository"
    description = "Clone or update a configured GitHub repository into a local workspace branch."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        if not owner or not repo:
            return {"error": "repository is required and must be allowed"}
        # A copy prepared only to be reviewed (``review_only``, the PR review bot) is read, never pushed: ``read``.
        operation = "read" if params.get("review_only") is True else "branch"
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation=operation)
        if denied:
            return denied
        base_branch = _string(params.get("base_branch")) or await _github_default_branch(context, owner, repo)
        branch_name = _string(params.get("branch_name")) or f"codex/{repo}"
        repo_path = _github_managed_repo_path(context, owner, repo)
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        clone_url = github_clone_url(context, owner, repo)
        git_env = await github_git_auth_env_async(context)
        # One preparation of this cache clone at a time, across processes (scm_cache_clone).
        async with cache_clone_lock(repo_path):
            cloned, failure = await _clone_or_set_origin(
                repo_path, clone_url=clone_url, git_env=git_env, base_branch=base_branch
            )
            if failure:
                return failure
            head_commit, failure = await _checkout_work_branch(
                repo_path, git_env=git_env, base_branch=base_branch, branch_name=branch_name
            )
            if failure:
                return failure
        return _prepared_result(
            context,
            owner=owner,
            repo=repo,
            repo_path=repo_path,
            base_branch=base_branch,
            branch_name=branch_name,
            cloned=cloned,
            clone_url=clone_url,
            head_commit=head_commit,
        )
