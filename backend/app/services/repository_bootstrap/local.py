from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from app.config import git_commit_identity
from app.services.execution_runtime.server_env import with_git_hardening
from app.services.git_http_auth import without_credentials
from app.services.repository_bootstrap.helpers import DEFAULT_GITIGNORE_LINES

_COMMIT_SHA = re.compile(r"[0-9a-f]{7,64}")


async def run_git(
    command: list[str], *, cwd: Path, timeout_sec: int = 120, env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    # Never interactive: the hardened environment drops an inherited askpass; the connection's
    # own auth (``env``) stays.
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=with_git_hardening(os.environ if env is None else env),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return 124, "", f"git command timed out after {timeout_sec}s"
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _git_failure(summary: str, code: str, exit_code: int) -> dict[str, object]:
    return {"error": summary, "error_code": code, "exit_code": exit_code}


def write_bootstrap_files(repo_path: Path, *, repo_name: str, create_readme: bool, create_gitignore: bool) -> list[str]:
    written: list[str] = []
    if create_readme:
        readme_path = repo_path / "README.md"
        if not readme_path.exists():
            readme_path.write_text(f"# {repo_name}\n", encoding="utf-8")
            written.append(str(readme_path))
    if create_gitignore:
        gitignore_path = repo_path / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text("\n".join(DEFAULT_GITIGNORE_LINES) + "\n", encoding="utf-8")
            written.append(str(gitignore_path))
    return written


async def _git_has_commits(repo_path: Path, *, timeout_sec: int) -> bool:
    exit_code, _, _ = await run_git(["git", "rev-parse", "--verify", "HEAD"], cwd=repo_path, timeout_sec=timeout_sec)
    return exit_code == 0


async def initialize_local_repository(
    *,
    repo_path: Path,
    repo_name: str,
    default_branch: str,
    create_readme: bool,
    create_gitignore: bool,
    initial_commit: bool,
    initial_commit_message: str,
    remote_url: str | None,
    timeout_sec: int,
    remote_git_env: dict[str, str] | None = None,
) -> dict[str, object]:
    repo_path.mkdir(parents=True, exist_ok=True)
    written_files = write_bootstrap_files(
        repo_path,
        repo_name=repo_name,
        create_readme=create_readme,
        create_gitignore=create_gitignore,
    )
    initialized = False
    remote_url = without_credentials(remote_url) if remote_url else remote_url  # never a credential in .git/config
    if not (repo_path / ".git").exists():
        exit_code, _, _ = await run_git(
            ["git", "init", "-b", default_branch], cwd=repo_path, timeout_sec=timeout_sec
        )
        if exit_code != 0:
            return _git_failure("git init failed", "repository_git_init_failed", exit_code)
        initialized = True

    for key, value in git_commit_identity():
        await run_git(["git", "config", key, value], cwd=repo_path, timeout_sec=timeout_sec)
    await run_git(["git", "branch", "-M", default_branch], cwd=repo_path, timeout_sec=timeout_sec)

    if remote_url:
        exit_code, _, _ = await run_git(
            ["git", "remote", "get-url", "origin"], cwd=repo_path, timeout_sec=timeout_sec
        )
        if exit_code == 0:
            await run_git(["git", "remote", "set-url", "origin", remote_url], cwd=repo_path, timeout_sec=timeout_sec)
        else:
            exit_code, _, _ = await run_git(
                ["git", "remote", "add", "origin", remote_url], cwd=repo_path, timeout_sec=timeout_sec
            )
            if exit_code != 0:
                return _git_failure("git remote add failed", "repository_git_remote_add_failed", exit_code)

    commit_created = False
    if initial_commit and not await _git_has_commits(repo_path, timeout_sec=timeout_sec):
        exit_code, _, _ = await run_git(["git", "add", "-A"], cwd=repo_path, timeout_sec=timeout_sec)
        if exit_code != 0:
            return _git_failure("git add failed", "repository_git_add_failed", exit_code)
        exit_code, _, _ = await run_git(
            ["git", "commit", "--allow-empty", "-m", initial_commit_message],
            cwd=repo_path,
            timeout_sec=timeout_sec,
        )
        if exit_code != 0:
            return _git_failure("git commit failed", "repository_git_commit_failed", exit_code)
        commit_created = True

    if remote_url and initial_commit:
        exit_code, _, _ = await run_git(
            ["git", "push", "-u", "origin", default_branch],
            cwd=repo_path,
            timeout_sec=timeout_sec,
            env=remote_git_env or None,  # a Bearer sign-in's header as GIT_CONFIG_* variables (git_http_auth)
        )
        if exit_code != 0:
            return _git_failure("git push failed", "repository_git_push_failed", exit_code)

    exit_code, stdout, _ = await run_git(["git", "rev-parse", "HEAD"], cwd=repo_path, timeout_sec=timeout_sec)
    head_commit = stdout.strip() if exit_code == 0 and _COMMIT_SHA.fullmatch(stdout.strip()) else None
    return {
        "initialized": initialized,
        "commit_created": commit_created,
        "written_files": written_files,
        "head_commit": head_commit,
    }
