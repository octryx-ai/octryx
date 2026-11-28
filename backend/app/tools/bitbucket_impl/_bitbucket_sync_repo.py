"""Bitbucket repository preparation and commit tools."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.tools.context import ToolContext

from ...config import git_commit_identity
from ...services.project_resource_policy import require_project_repository_operation
from ...services.source_control import SourceControlOperation
from ..connectors.scm_cache_clone import cache_clone_lock
from ._bitbucket_cloud import cloud_context
from ._bitbucket_internal_core import (
    _bitbucket_clone_url,
    _bitbucket_git_auth_env_async,
    _detect_default_branch,
    _is_repo_allowed,
    _managed_repo_path,
    _mask_clone_url,
    _run_git,
)
from ._bitbucket_source_control import bitbucket_source_control_metadata
from ._bitbucket_write_gate import bitbucket_write_refusal


def _git_failure(error: str, exit_code: int, stderr: str = "", **extra: Any) -> dict[str, Any]:
    from ..connectors.git_errors import git_failure

    return git_failure(error, exit_code, stderr, **extra)


# (error_code, fixed sentence, status for the run's failure class, stderr markers); first match wins. Auth comes
# before network: "unable to access '...': The requested URL returned error: 403" names both.
_PUSH_FAILURES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("push_auth_failed", "the service did not accept the connection's credentials", "denied",
     ("authentication failed", "could not read username", "invalid username or password", "returned error: 401",
      "returned error: 403", "permission denied", "access denied", "not authorized", "unauthorized",
      "forbidden")),
    ("push_rejected_non_fast_forward", "the remote branch has commits the working copy does not have "
     "(non-fast-forward)", "", ("non-fast-forward", "fetch first", "updates were rejected", "[rejected]",
                                "stale info")),
    ("push_declined_by_hook", "a hook or branch restriction of the service declined the push", "",
     ("hook declined", "pre-receive", "protected branch", "branch permission", "[remote rejected]",
      "repository rule violations", "push protection", "gh013", "gh006")),
    ("push_repository_not_found", "the service does not know the repository", "",
     ("repository not found", "does not exist", "returned error: 404", "not found")),
    ("push_network", "the service could not be reached (network or timeout)", "timeout",
     ("could not resolve host", "connection timed out", "connection refused", "failed to connect",
      "operation timed out", "timed out", "unable to access", "rpc failed", "early eof", "ssl certificate", "gnutls",
      "connection reset", "network is unreachable", "the remote end hung up")),
)


def _push_failure(stderr: str, exit_code: int, error: str = "git push failed", **extra: Any) -> dict[str, Any]:
    text = str(stderr or "").lower()
    for code, sentence, status, markers in _PUSH_FAILURES:
        if any(marker in text for marker in markers):
            return {"error": f"{error}: {sentence}", "error_code": code, "exit_code": int(exit_code),
                    **({"status": status} if status else {}), **extra}
    if exit_code == 124:  # ``_run_git``'s own timeout
        return {"error": f"{error}: the push timed out", "error_code": "push_network", "exit_code": 124,
                "status": "timeout", **extra}
    return _git_failure(error, exit_code, **extra)


async def _track_pushed_branch(repo_path: Path, push_target: str, branch: str, timeout_sec: int) -> None:
    if push_target:
        await _run_git(["git", "update-ref", f"refs/remotes/origin/{branch}", "HEAD"], cwd=repo_path,
                       timeout_sec=timeout_sec)


async def _remote_is_empty(clone_url: str, git_env: dict[str, str] | None, timeout_sec: int) -> bool:
    from ...services.knowledge.sources.sync.git_clone import advertises_no_ref

    exit_code, stdout, _ = await _run_git(["git", "ls-remote", clone_url], timeout_sec=timeout_sec, env=git_env)
    return exit_code == 0 and advertises_no_ref(stdout.encode("ascii", "replace"))


async def _prepare_empty(
    repo_path: Path, clone_url: str, branch_name: str, git_env: dict[str, str] | None, timeout_sec: int
) -> dict[str, Any] | None:
    if not (repo_path / ".git").exists():
        exit_code, _, git_err = await _run_git(
            ["git", "clone", clone_url, str(repo_path)], timeout_sec=timeout_sec, env=git_env
        )
        if exit_code != 0:
            return _git_failure("git clone failed", exit_code, git_err)
    exit_code, _, git_err = await _run_git(
        ["git", "check-ref-format", "--branch", branch_name], cwd=repo_path, timeout_sec=timeout_sec
    )
    if exit_code != 0:
        return _git_failure("git branch name invalid", exit_code, git_err)
    exit_code, _, git_err = await _run_git(
        ["git", "symbolic-ref", "HEAD", f"refs/heads/{branch_name}"], cwd=repo_path, timeout_sec=timeout_sec
    )
    if exit_code != 0:
        return _git_failure("git checkout branch failed", exit_code, git_err)
    return None


@dataclass
class _BaseCheckout:
    # The base branch the working copy is on, how it got there and the branches tried.
    base_branch: str
    cloned: bool = False
    fallback_used: bool = False
    empty: bool = False
    attempted: list[str] = field(default_factory=list)


_FALLBACK, _EMPTY, _ON_BASE = "fallback", "empty", "on_base"


class PrepareBitbucketRepository:
    name = "prepare_bitbucket_repository"
    description = (
        "Ensure an allowed Bitbucket repository is cloned locally, "
        "pulled to the latest base branch, and switched to a new working branch."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        refused = await _prepare_refusal(params, context, project_key, repo_slug)
        if refused:
            return refused
        requested_base_branch = str(params.get("base_branch") or "").strip()
        detected_base_branch = await _detect_default_branch(context, project_key, repo_slug)
        branch_name = _work_branch_name(params, repo_slug)
        timeout_sec = max(10, min(int(params.get("timeout_sec") or 180), 600))
        try:
            repo_path = _managed_repo_path(context, project_key, repo_slug)
            repo_path.parent.mkdir(parents=True, exist_ok=True)
            clone_url = _bitbucket_clone_url(context, project_key, repo_slug)
            git_env = await _bitbucket_git_auth_env_async(context, clone_url)
        except ValueError as exc:
            return {"error": str(exc)}
        git = _Git(repo_path, clone_url, git_env, timeout_sec)
        # One preparation of this cache clone at a time, across processes (scm_cache_clone).
        async with cache_clone_lock(repo_path):
            checkout = _BaseCheckout(base_branch=requested_base_branch or detected_base_branch)
            for candidate_branch in [checkout.base_branch, detected_base_branch]:
                if candidate_branch in checkout.attempted:
                    continue
                checkout.attempted.append(candidate_branch)
                fallback_allowed = bool(requested_base_branch) and candidate_branch == requested_base_branch \
                    and detected_base_branch != requested_base_branch
                outcome = await _checkout_base(git, checkout, candidate_branch, fallback_allowed)
                if outcome == _FALLBACK:
                    checkout.fallback_used = True
                    continue
                if outcome == _EMPTY:
                    checkout.empty = True
                elif isinstance(outcome, dict):
                    return outcome
                else:
                    checkout.base_branch = candidate_branch
                break
            head = await _start_work_branch(git, checkout, branch_name)
            if isinstance(head, dict):
                return head
        return _prepared(context, project_key, repo_slug, git, branch_name, checkout, head)


@dataclass(frozen=True)
class _Git:
    repo_path: Path
    clone_url: str
    env: dict[str, str] | None
    timeout_sec: int

    async def run(self, args: list[str], *, here: bool = True) -> tuple[int, str, str]:
        return await _run_git(args, cwd=self.repo_path if here else None, timeout_sec=self.timeout_sec, env=self.env)


async def _prepare_refusal(params: dict, context: ToolContext, project_key: str, repo_slug: str) -> dict | None:
    if not project_key or not repo_slug:
        return {"error": "project_key and repo_slug are required"}
    if not _is_repo_allowed(context, project_key, repo_slug):
        return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}
    try:
        await require_project_repository_operation(
            context.db,
            project_ids=context.project_ids,
            provider="bitbucket",
            # A copy prepared only to be reviewed (the PR review bot) is read, never pushed.
            operation="read" if params.get("review_only") is True else "branch",
            repository_refs=[repo_slug, f"{project_key}/{repo_slug}"],
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    return None


def _work_branch_name(params: dict, repo_slug: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    branch_prefix = str(params.get("branch_prefix") or "codex").strip().strip("/") or "codex"
    ticket_id = str(params.get("ticket_id") or "").strip().lower().replace(" ", "-")
    default_branch_name = (f"{branch_prefix}/{ticket_id}/readme-{repo_slug}-{timestamp}" if ticket_id
                           else f"{branch_prefix}/readme-{repo_slug}-{timestamp}")
    return str(params.get("branch_name") or "").strip() or default_branch_name


async def _checkout_base(git: _Git, checkout: _BaseCheckout, candidate_branch: str,
                         fallback_allowed: bool) -> str | dict[str, Any]:
    # _ON_BASE, _FALLBACK (the requested branch failed, the detected one is next), _EMPTY, or a failure.
    if not (git.repo_path / ".git").exists():
        exit_code, _, git_err = await git.run(
            ["git", "clone", "--branch", candidate_branch, git.clone_url, str(git.repo_path)], here=False)
        if exit_code != 0:
            return await _base_unavailable(git, fallback_allowed, _git_failure("git clone failed", exit_code, git_err))
        checkout.cloned = True
    else:
        exit_code, _, git_err = await git.run(["git", "remote", "set-url", "origin", git.clone_url])
        if exit_code != 0:
            return _git_failure("git remote set-url failed", exit_code, git_err)
    exit_code, _, git_err = await git.run(["git", "fetch", "--prune", "origin"])
    if exit_code != 0:
        return _git_failure("git fetch failed", exit_code, git_err)
    # Exactly the fetched remote base, whatever the local base branch holds; no pull (scm_cache_clone).
    exit_code, _, git_err = await git.run(["git", "checkout", "-f", "-B", candidate_branch,
                                           f"origin/{candidate_branch}"])
    if exit_code != 0:
        return await _base_unavailable(git, fallback_allowed,
                                       _git_failure("git checkout base branch failed", exit_code, git_err))
    exit_code, _, git_err = await git.run(["git", "clean", "-fd"])
    if exit_code != 0:
        return _git_failure("git clean failed", exit_code, git_err)
    return _ON_BASE


async def _base_unavailable(git: _Git, fallback_allowed: bool, failure: dict[str, Any]) -> str | dict[str, Any]:
    if fallback_allowed:
        return _FALLBACK
    if await _remote_is_empty(git.clone_url, git.env, git.timeout_sec):
        return _EMPTY
    return failure


async def _start_work_branch(git: _Git, checkout: _BaseCheckout, branch_name: str) -> str | dict[str, Any]:
    # The head commit on the work branch ("" when the repository is empty), or a failure.
    if checkout.empty:
        # No commit, no default branch: the work branch starts unborn (module doc).
        failed = await _prepare_empty(git.repo_path, git.clone_url, branch_name, git.env, git.timeout_sec)
        if failed is not None:
            return failed
        checkout.cloned, checkout.base_branch = (git.repo_path / ".git").exists(), ""
        return ""
    exit_code, _, git_err = await git.run(["git", "checkout", "-B", branch_name])
    if exit_code != 0:
        return _git_failure("git checkout branch failed", exit_code, git_err)
    exit_code, head_stdout, _ = await git.run(["git", "rev-parse", "HEAD"])
    if exit_code != 0:
        return _git_failure("git rev-parse failed", exit_code)
    return head_stdout


def _prepared(context: ToolContext, project_key: str, repo_slug: str, git: _Git, branch_name: str,
              checkout: _BaseCheckout, head_stdout: str) -> dict[str, Any]:
    workspace_root = Path(context.workspace_root or Path.cwd()).resolve()
    relative_repo_path = git.repo_path.relative_to(workspace_root)
    empty = {"repository_empty": True} if checkout.empty else {}
    source_control = bitbucket_source_control_metadata(
        SourceControlOperation.PREPARE_REPOSITORY,
        project_key=project_key,
        repo_slug=repo_slug,
        status="prepared",
        output={"workspace_ref": str(relative_repo_path), "head_commit": head_stdout.strip(),
                "branch_name": branch_name, "base_branch": checkout.base_branch},
        evidence={"cloned": checkout.cloned, "fallback_used": checkout.fallback_used,
                  "remote_url": _mask_clone_url(git.clone_url), **empty},
    )
    return {
        "project_key": project_key,
        "repo_slug": repo_slug,
        "local_path": str(git.repo_path),
        "relative_path": str(relative_repo_path),
        "base_branch": checkout.base_branch,
        "branch_name": branch_name,
        "cloned": checkout.cloned,
        "fallback_used": checkout.fallback_used,
        "attempted_base_branches": checkout.attempted,
        "remote_url": _mask_clone_url(git.clone_url),
        "head_commit": head_stdout.strip(),
        "source_control": source_control,
        **empty,
    }


class CommitAndPushRepositoryBranch:
    name = "commit_and_push_repository_branch"
    description = "Commit local repository changes and push the current working branch to origin for review."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        local_path = str(params.get("local_path") or "").strip()
        commit_message = str(params.get("commit_message") or params.get("message") or "").strip()
        if not local_path or not commit_message:
            return {"error": "local_path and commit_message are required"}
        workspace_root = Path(context.workspace_root or Path.cwd()).resolve()
        repo_path = Path(local_path).expanduser()
        repo_path = repo_path.resolve() if repo_path.is_absolute() else (workspace_root / repo_path).resolve()
        if workspace_root not in repo_path.parents and repo_path != workspace_root:
            return {"error": f"local_path must stay inside workspace root: {workspace_root}"}
        if not (repo_path / ".git").exists():
            return {"error": "local_path is not a git repository"}
        refused = await _write_refusal(params, context, repo_path)
        if refused:
            return refused
        push_target, refused = _cloud_push_target(context, params)
        if refused:
            return refused
        timeout_sec = max(10, min(int(params.get("timeout_sec") or 180), 600))
        branch_name = str(params.get("branch_name") or "").strip()
        # A repository the Workspace registered read-only is never pushed to: refused before any commit or push.
        refused = await bitbucket_write_refusal(
            context, remote_urls=await _push_destinations(repo_path, push_target, timeout_sec)
        )
        if refused:
            return refused
        exit_code, stdout, _ = await _run_git(["git", "status", "--porcelain"], cwd=repo_path, timeout_sec=timeout_sec)
        if exit_code != 0:
            return _git_failure("git status failed", exit_code)
        if params.get("push_only") is True and stdout.strip():
            # push_only (the platform's fast-forward of an adopted branch): never a commit.
            return {"error": "push_only: the working copy has uncommitted changes"}
        if not stdout.strip():
            return await _push_clean_copy(context, repo_path, push_target, branch_name, timeout_sec)
        return await _commit_and_push(context, repo_path, push_target, branch_name, commit_message, timeout_sec)


async def _write_refusal(params: dict, context: ToolContext, repo_path: Path) -> dict[str, Any] | None:
    try:
        await require_project_repository_operation(
            context.db,
            project_ids=context.project_ids,
            provider="bitbucket",
            operation="write",
            repository_refs=[
                str(repo_path),
                str(repo_path.name),
                str(params.get("repo_slug") or "").strip(),
                str(params.get("repository") or "").strip(),
            ],
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    return None


async def _origin_or_target(repo_path: Path, push_target: str, timeout_sec: int) -> str:
    exit_code, stdout, _ = await _run_git(["git", "remote", "get-url", "origin"], cwd=repo_path,
                                          timeout_sec=timeout_sec)
    return push_target or (stdout.strip() if exit_code == 0 else "")


async def _push_clean_copy(context: ToolContext, repo_path: Path, push_target: str, branch_name: str,
                           timeout_sec: int) -> dict[str, Any]:
    # Everything is committed already, and delivery stays idempotent: the workspace branch is pushed and a
    # local-mirror origin chased, so a retry after a partial delivery reaches the real remote.
    current_branch = branch_name
    if not current_branch:
        exit_code, branch_stdout, _ = await _run_git(["git", "branch", "--show-current"], cwd=repo_path,
                                                     timeout_sec=timeout_sec)
        current_branch = branch_stdout.strip() if exit_code == 0 else ""
    upstream_push = None
    pushed_head = ""  # set only when this call pushed the branch: the remote then holds it
    origin_url = await _origin_or_target(repo_path, push_target, timeout_sec) if current_branch else ""
    if origin_url:
        try:
            git_env = await _bitbucket_git_auth_env_async(context, origin_url)
        except ValueError as exc:
            return {"error": str(exc), "local_path": str(repo_path)}
        push_exit_code, _, push_stderr = await _run_git(_push_command(push_target, current_branch), cwd=repo_path,
                                                        timeout_sec=timeout_sec, env=git_env)
        if push_exit_code != 0:
            return _push_failure(push_stderr, push_exit_code)
        await _track_pushed_branch(repo_path, push_target, current_branch, timeout_sec)
        head_exit_code, head_out, _ = await _run_git(["git", "rev-parse", "HEAD"], cwd=repo_path,
                                                     timeout_sec=timeout_sec)
        pushed_head = head_out.strip() if head_exit_code == 0 else ""
        upstream_push = None if push_target else await _push_local_mirror_upstream(
            context, workspace_remote_url=origin_url, branch_name=current_branch, timeout_sec=timeout_sec)
        if upstream_push and upstream_push.get("error"):
            return {"error": "push reached the local mirror but the upstream push failed",
                    "upstream_push": upstream_push, "branch_name": current_branch}
    return {
        "status": "no_changes",
        "local_path": str(repo_path),
        **({"branch_name": current_branch, "head_commit": pushed_head} if pushed_head else {}),
        **({"upstream_push": upstream_push} if upstream_push else {}),
        "source_control": bitbucket_source_control_metadata(
            SourceControlOperation.PUSH,
            project_key="",
            repo_slug=repo_path.name,
            status="no_changes",
            output={"workspace_ref": str(repo_path)},
            evidence={"reason": "git_status_clean"},
        ),
    }


async def _commit_and_push(context: ToolContext, repo_path: Path, push_target: str, branch_name: str,
                           commit_message: str, timeout_sec: int) -> dict[str, Any]:
    for key, value in git_commit_identity():
        await _run_git(["git", "config", key, value], cwd=repo_path, timeout_sec=timeout_sec)
    exit_code, _, git_err = await _run_git(["git", "add", "-A"], cwd=repo_path, timeout_sec=timeout_sec)
    if exit_code != 0:
        return _git_failure("git add failed", exit_code, git_err)
    if not branch_name:
        exit_code, stdout, _ = await _run_git(["git", "branch", "--show-current"], cwd=repo_path,
                                              timeout_sec=timeout_sec)
        if exit_code != 0:
            return _git_failure("git branch --show-current failed", exit_code)
        branch_name = stdout.strip()
    if not branch_name:
        return {"error": "Could not determine current branch name"}
    exit_code, _, git_err = await _run_git(["git", "commit", "-m", commit_message], cwd=repo_path,
                                           timeout_sec=timeout_sec)
    if exit_code != 0:
        return _git_failure("git commit failed", exit_code, git_err)
    remote_url = await _origin_or_target(repo_path, push_target, timeout_sec)
    try:
        git_env = await _bitbucket_git_auth_env_async(context, remote_url) if remote_url else None
    except ValueError as exc:
        return {"error": str(exc)}
    exit_code, _, push_stderr = await _run_git(_push_command(push_target, branch_name), cwd=repo_path,
                                               timeout_sec=timeout_sec, env=git_env)
    if exit_code != 0:
        return _push_failure(push_stderr, exit_code)
    await _track_pushed_branch(repo_path, push_target, branch_name, timeout_sec)
    exit_code, head_stdout, _ = await _run_git(["git", "rev-parse", "HEAD"], cwd=repo_path, timeout_sec=timeout_sec)
    if exit_code != 0:
        return _git_failure("git rev-parse failed", exit_code)
    head_commit = head_stdout.strip()
    # Mirror-based workspaces clone from the platform's local repository mirror; a push to the workspace origin lands
    # only in that mirror. Chase the chain so the branch reaches the real remote too.
    upstream_push = None if push_target else await _push_local_mirror_upstream(
        context, workspace_remote_url=remote_url, branch_name=branch_name, timeout_sec=timeout_sec)
    if upstream_push and upstream_push.get("error"):
        return {"error": "push reached the local mirror but the upstream push failed", "upstream_push": upstream_push,
                "branch_name": branch_name, "head_commit": head_commit}
    return {
        "status": "pushed",
        **({"upstream_push": upstream_push} if upstream_push else {}),
        "local_path": str(repo_path),
        "branch_name": branch_name,
        "commit_message": commit_message,
        "head_commit": head_commit,
        "source_control": bitbucket_source_control_metadata(
            SourceControlOperation.PUSH,
            project_key="",
            repo_slug=repo_path.name,
            status="pushed",
            output={"workspace_ref": str(repo_path), "branch_name": branch_name, "head_commit": head_commit},
            evidence={"provider_operation": "bitbucket_commit_and_push"},
        ),
    }


def _cloud_push_target(context: ToolContext, params: dict) -> tuple[str, dict[str, Any] | None]:
    if not cloud_context(context):
        return "", None
    project_key = str(params.get("project_key") or "").strip()
    repo_slug = str(params.get("repo_slug") or "").strip()
    if not project_key or not repo_slug:
        return "", {"error": "project_key and repo_slug are required to push to Bitbucket Cloud"}
    if not _is_repo_allowed(context, project_key, repo_slug):
        return "", {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}
    return _bitbucket_clone_url(context, project_key, repo_slug), None


async def _origin_urls(cwd: Path, timeout_sec: int) -> list[str]:
    urls: list[str] = []
    for push in ([], ["--push"]):
        exit_code, stdout, _ = await _run_git(
            ["git", "remote", "get-url", *push, "--all", "origin"], cwd=cwd, timeout_sec=timeout_sec
        )
        if exit_code == 0:
            urls += [line.strip() for line in stdout.splitlines() if line.strip()]
    return list(dict.fromkeys(urls))


async def _push_destinations(repo_path: Path, push_target: str, timeout_sec: int) -> list[str]:
    if push_target:
        return [push_target]
    urls = await _origin_urls(repo_path, timeout_sec)
    for url in list(urls):
        mirror_path = _local_mirror(url)
        if mirror_path is not None:
            urls += await _origin_urls(mirror_path, timeout_sec)
    return urls


def _local_mirror(remote_url: str) -> Path | None:
    if not remote_url or "://" in remote_url or remote_url.startswith("git@"):
        return None
    mirror_path = Path(str(remote_url).strip()).expanduser()
    if not (mirror_path / ".git").exists() and not (mirror_path / "HEAD").exists():
        return None
    return mirror_path


def _push_command(push_target: str, branch: str) -> list[str]:
    if push_target:  # an explicit URL: the branch ref goes there and nowhere else
        return ["git", "push", push_target, f"refs/heads/{branch}:refs/heads/{branch}"]
    return ["git", "push", "--set-upstream", "origin", branch]


async def _push_local_mirror_upstream(
    context: ToolContext,
    *,
    workspace_remote_url: str,
    branch_name: str,
    timeout_sec: int,
) -> dict[str, Any] | None:
    mirror_path = _local_mirror(str(workspace_remote_url or "").strip())
    if mirror_path is None:
        return None
    exit_code, remote_stdout, _ = await _run_git(
        ["git", "remote", "get-url", "origin"], cwd=mirror_path, timeout_sec=timeout_sec
    )
    if exit_code != 0:
        return {"error": "local mirror has no origin remote", "mirror_path": str(mirror_path)}
    upstream_url = remote_stdout.strip()
    if not upstream_url or ("://" not in upstream_url and not upstream_url.startswith("git@")):
        return {"error": "local mirror origin is not a real remote", "mirror_path": str(mirror_path)}
    try:
        git_env = await _bitbucket_git_auth_env_async(context, upstream_url)
    except ValueError as exc:
        return {"error": str(exc), "mirror_path": str(mirror_path)}
    exit_code, _, push_stderr = await _run_git(
        ["git", "push", "origin", f"{branch_name}:{branch_name}"],
        cwd=mirror_path,
        timeout_sec=timeout_sec,
        env=git_env,
    )
    if exit_code != 0:
        return _push_failure(push_stderr, exit_code, "upstream git push failed", mirror_path=str(mirror_path))
    return {"status": "pushed_upstream", "mirror_path": str(mirror_path), "upstream": _mask_clone_url(upstream_url)}
