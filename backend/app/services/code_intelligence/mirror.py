"""A shallow mirror of each Workspace repository for its code graph."""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.code_intelligence import CodeRepository

GIT_TIMEOUT = 900
MIRROR_KEY = "mirror"
REMOTE_PROVIDERS = ("github", "gitlab", "bitbucket")


class MirrorError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def mirror_root() -> Path | None:
    from ...config import get_settings

    raw = str(getattr(get_settings(), "code_mirror_root", "") or "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def mirror_path(repo: CodeRepository) -> Path | None:
    root = mirror_root()
    if root is None:
        return None
    return root / (repo.project_id or "_") / repo.id


async def _git(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        "git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never", *argv,
        cwd=str(cwd) if cwd else None, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _err = await asyncio.wait_for(process.communicate(), timeout=GIT_TIMEOUT)
    except TimeoutError:
        process.kill()
        return 124, ""
    return process.returncode or 0, out.decode("utf-8", "replace").strip()  # Git's stderr is never kept


async def _auth_env(db: AsyncSession, repo: CodeRepository) -> dict[str, str] | None:
    try:
        return await _provider_auth_env(db, repo)
    except ValueError as error:
        raise MirrorError("credential_refused", str(error)[:200]) from error


async def _provider_auth_env(db: AsyncSession, repo: CodeRepository) -> dict[str, str] | None:
    from ...tools.context import ToolContext
    from ..project.service import get_project_config
    from ..run_capability.worker_profiles import worker_tool_context_state

    context = ToolContext(user_id="", project_ids=[repo.project_id] if repo.project_id else [], roles=[],
                          session_id="", project_config=await get_project_config(repo.project_id, db), db=db,
                          run_capability=worker_tool_context_state("code_mirror_fetch"))
    provider = str(repo.provider or "").lower()
    if provider == "github":
        from ...tools.connectors.github_source_control_common import github_git_auth_env_async

        return await github_git_auth_env_async(context)
    if provider == "gitlab":
        from ...tools.connectors.gitlab_source_control_common import gitlab_git_auth_env_async

        return await gitlab_git_auth_env_async(context)
    if provider == "bitbucket":
        from ...tools.bitbucket_impl._bitbucket_internal_core import _bitbucket_git_auth_env_async

        return await _bitbucket_git_auth_env_async(context, str(repo.remote_url))
    return None


def _size(path: Path) -> int:
    total = 0
    for folder, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(folder) / name).stat().st_size
            except OSError:
                continue
    return total


async def ensure_mirror(db: AsyncSession, repo: CodeRepository) -> dict[str, Any]:
    target = mirror_path(repo)
    if target is None:
        raise MirrorError("mirror_disabled", "no code_mirror_root is set")
    if str(repo.provider or "").lower() not in REMOTE_PROVIDERS or not repo.remote_url:
        raise MirrorError("no_remote", "the repository has no remote to mirror")
    env = await _auth_env(db, repo) or {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    branch = str(repo.default_branch or "").strip()
    if not (target / ".git").is_dir():
        if target.exists():
            shutil.rmtree(target)  # a half-made clone of an earlier attempt (only ever inside the mirror root)
        target.parent.mkdir(parents=True, exist_ok=True)
        argv = ["clone", "--depth", "1", "--single-branch", "--no-tags",
                *(["--branch", branch] if branch else []), str(repo.remote_url), str(target)]
        code, _out = await _git(argv, env=env)
        if code != 0:
            raise MirrorError("clone_failed", f"git clone exited {code}")
    else:
        ref = branch or "HEAD"
        code, _out = await _git(["fetch", "--depth", "1", "--no-tags", "origin", ref], cwd=target, env=env)
        if code != 0:
            raise MirrorError("fetch_failed", f"git fetch exited {code}")
        code, _out = await _git(["reset", "--hard", "FETCH_HEAD"], cwd=target)
        if code != 0:
            raise MirrorError("fetch_failed", f"git reset exited {code}")
    _code, head = await _git(["rev-parse", "HEAD"], cwd=target)
    record = {"path": str(target), "head": head[:40], "bytes": await asyncio.to_thread(_size, target),
              "fetched_at": datetime.now(UTC).isoformat(), "branch": branch or None}
    repo.repo_root = str(target)
    repo.config_json = {**dict(repo.config_json or {}), MIRROR_KEY: record}
    return record


def mirror_status(repo: CodeRepository) -> dict[str, Any] | None:
    record = dict(repo.config_json or {}).get(MIRROR_KEY)
    return dict(record) if isinstance(record, dict) else None


__all__ = ["MIRROR_KEY", "MirrorError", "ensure_mirror", "mirror_path", "mirror_root", "mirror_status"]
