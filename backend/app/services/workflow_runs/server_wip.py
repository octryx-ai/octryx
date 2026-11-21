"""The Server pushes a device run's work in progress (``octryx-wip/<run id>``) from the change the device reported.

Why: when the launcher pushed the WIP with the person's own git sign-in (osxkeychain), every device turn could log
``wip_failed …
push_refused`` once that sign-in no longer had a
Bitbucket entry ("Authentication failed"). Repository tokens never go to a device (least privilege), so the
Server builds the WIP commit itself from ``context.device_change`` (the patch against
the run's base, which it already holds for review and push) and pushes it with the Workspace's connection
(``origin_auth.origin_git_env``, the credential the Bitbucket tools and the server prepare use).

The server working copy is never touched: the commit is built in a temporary index (``read-tree`` of the base,
``apply --cached``), only objects and the private ref ``refs/octryx-wip/<run>`` are written. Each WIP commit has the
previous remote WIP as its parent, so every push is a fast-forward, never forced, and only to ``octryx-wip/<run>`` (the
name is generated here). Handover and restore (``server_prepare.restore_run_wip``) therefore work without any
personal sign-in on the Mac. A device push that worked stays as it is; a device push that failed is a fallback and
never an error event.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from . import safe_git

PREFIX = "octryx-wip"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def wip_branch(run_id: str) -> str:
    return f"{PREFIX}/{re.sub(r'[^A-Za-z0-9._-]', '-', run_id).strip('-.')[:60] or 'x'}"


async def _out(root: Path, *args: str, env: dict[str, str] | None = None, stdin: bytes | None = None) -> str:
    code, out, _err = await safe_git.git(root, *args, env=env, stdin=stdin)
    return out.strip() if code == 0 else ""


async def build_and_push(root: Path, run_id: str, base: str, patch: str,
                         git_env: dict[str, str] | None) -> dict[str, Any]:
    """``{state: pushed|unchanged|failed, branch, sha?, reason?}`` for ``base`` + ``patch``; never raises."""
    branch = wip_branch(run_id)
    local = f"refs/{branch}"
    if not _SHA.match(base) or not patch.strip():
        return {"state": "failed", "branch": branch, "reason": "no_change"}
    await safe_git.git(root, "fetch", "--no-tags", "--quiet", "origin", f"+refs/heads/{branch}:{local}", env=git_env)
    previous = await _out(root, "rev-parse", "--verify", "--quiet", local)
    with tempfile.TemporaryDirectory(prefix="octryx-wip-index-") as folder:
        index = {**(git_env or os.environ), "GIT_INDEX_FILE": str(Path(folder) / "index")}
        if not await _out(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"):
            return {"state": "failed", "branch": branch, "reason": "base_unavailable"}
        await safe_git.git(root, "read-tree", base, env=index)
        code, _out_text, error = await safe_git.git(root, "apply", "--cached", "--binary", "--whitespace=nowarn", "-",
                                                    env=index, stdin=patch.encode())
        if code != 0:
            return {"state": "failed", "branch": branch, "reason": "patch_does_not_apply",
                    "detail": (error.strip().splitlines() or [""])[-1][:200]}
        tree = await _out(root, "write-tree", env=index)
    if not tree:
        return {"state": "failed", "branch": branch, "reason": "git_failed"}
    if _SHA.match(previous) and tree == await _out(root, "rev-parse", f"{previous}^{{tree}}"):
        return {"state": "unchanged", "branch": branch, "sha": previous}
    parent = previous if _SHA.match(previous) else base
    commit = await _out(root, "commit-tree", tree, "-p", parent, "-m", f"WIP of workflow run {run_id}")
    if not _SHA.match(commit):
        return {"state": "failed", "branch": branch, "reason": "git_failed"}
    await safe_git.git(root, "update-ref", local, commit)
    code, _push_out, error = await safe_git.git(root, "push", "--no-verify", "--no-follow-tags", "--quiet", "origin",
                                                f"{commit}:refs/heads/{branch}", env=git_env)
    if code != 0:
        reason = "push_auth_failed" if "auth" in error.lower() else "push_refused"
        return {"state": "failed", "branch": branch, "reason": reason}
    return {"state": "pushed", "branch": branch, "sha": commit}


async def push_from_device_change(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    """The run's WIP pushed by the Server from ``context.device_change``; ``None`` when there is nothing to push."""
    from .workspace.origin_auth import origin_git_env

    context = dict(run.context or {})
    change = dict(context.get("device_change") or {})
    local_path = str(context.get("local_path") or "")
    patch = str(change.get("patch") or "")
    if change.get("base_unavailable") or change.get("truncated") or not patch.strip() or not local_path:
        return None
    root = Path(local_path)
    if not (root / ".git").exists():
        return None
    base = str(change.get("base") or context.get("base_sha") or "")
    return await build_and_push(root, run.id, base, patch, await origin_git_env(db, run, root))


__all__ = ["build_and_push", "push_from_device_change", "wip_branch"]
