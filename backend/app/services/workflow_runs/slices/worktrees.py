"""The git side of a slice: its own worktree branch, its commit, its merge into the run's working copy.

All git runs on the server in the run's working copy (``context.local_path``) and the slices' worktrees beside it;
commits use a fixed platform identity and git never runs what the working copy configures (``safe_git``: no
hooks). A merge that conflicts is aborted at once (the working copy stays as it was) and reports the conflicting
files — a gate failure that loops back, never a half-merged tree.
"""

from __future__ import annotations

from pathlib import Path

from ..safe_git import git


async def head(cwd: Path) -> str:
    code, out, _ = await git(cwd, "rev-parse", "HEAD")
    return out.strip() if code == 0 else ""


async def ensure_worktree(main: Path, path: Path, branch: str) -> str:
    """The slice's worktree on ``branch`` from the working copy's HEAD (reused when it exists); '' or an error."""
    if (path / ".git").exists():
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    code, _out, err = await git(main, "worktree", "add", "-B", branch, str(path), "HEAD")
    return "" if code == 0 else (err.strip().splitlines() or ["worktree_failed"])[-1][:300]


async def reset_to(path: Path, ref: str) -> bool:
    """Start the slice over from ``ref`` (a re-delegation after a conflict: the slice builds on the merged state)."""
    code, _out, _err = await git(path, "reset", "--hard", ref)
    if code == 0:
        await git(path, "clean", "-fd")
    return code == 0


async def commit_all(path: Path, message: str) -> str:
    """Commit everything the child changed in its worktree; the new HEAD ('' when nothing changed or git failed)."""
    await git(path, "add", "-A")
    code, _out, _err = await git(path, "commit", "-q", "-m", message[:200])
    return await head(path) if code == 0 else ""


async def changed_files(path: Path, base: str) -> list[str]:
    code, out, _ = await git(path, "diff", "--name-only", base, "HEAD")
    return [line for line in out.splitlines() if line.strip()][:200] if code == 0 else []


async def merge(main: Path, branch: str, message: str) -> tuple[bool, list[str]]:
    """``(merged, conflicting files)``; a conflict is aborted so the working copy stays unchanged."""
    code, _out, _err = await git(main, "merge", "--no-ff", "--no-edit", "-m", message[:200], branch)
    if code == 0:
        return True, []
    _c, conflicts, _e = await git(main, "diff", "--name-only", "--diff-filter=U")
    await git(main, "merge", "--abort")
    return False, [line for line in conflicts.splitlines() if line.strip()][:50] or ["merge_failed"]


__all__ = [
    "changed_files",
    "commit_all",
    "ensure_worktree",
    "head",
    "merge",
    "reset_to",
]
