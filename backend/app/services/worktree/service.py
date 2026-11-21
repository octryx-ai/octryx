"""Git Worktree Isolation Service.

Creates and manages git worktrees so each agent session can work in an isolated
copy of the repository without affecting the main working tree.

Worktrees are stored under data/worktrees/{session_id}/
They are cleaned up when the session ends or explicitly via cleanup().
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..execution_runtime import execute_with_runtime

_DATA_DIR = Path(__file__).resolve().parents[4] / "data"


@dataclass
class Worktree:
    id: str
    session_id: str
    branch: str
    path: Path
    git_root: Path  # The original repo root


async def _run_git(*args: str, cwd: str | Path | None = None, check: bool = True) -> tuple[int, str, str]:
    cmd = ["git", *args]
    effective_cwd = Path(str(cwd)).resolve() if cwd else Path.cwd().resolve()
    result = await execute_with_runtime(
        db=None,
        project_config=None,
        command=cmd,
        cwd=effective_cwd,
        workspace_root=effective_cwd,
        timeout_sec=60,
        guard_foreign_build=False,  # the platform's own git (fixed subcommand), not an agent command
    )
    out = result.stdout.strip()
    err = result.stderr.strip()
    return_code = result.exit_code if result.exit_code is not None else 124
    if check and return_code != 0:
        # Closed facts only: git output can carry credentialed remote URLs and internal paths.
        raise RuntimeError(f"git_command_failed subcommand={args[0]} exit_code={return_code}")
    return return_code, out, err


async def _find_git_root(path: str | Path) -> Path | None:
    """Walk up from path to find the git root."""
    rc, out, _ = await _run_git("rev-parse", "--show-toplevel", cwd=path, check=False)
    if rc == 0 and out:
        return Path(out)
    return None


class WorktreeService:
    """Create and manage git worktrees for isolated agent sessions."""

    def __init__(self) -> None:
        self._worktrees: dict[str, Worktree] = {}

    async def create(
        self,
        session_id: str,
        workspace_root: str,
        branch_prefix: str = "agent",
    ) -> Worktree:
        """Create a new git worktree for the given session.

        Creates an orphan branch ``{branch_prefix}/{session_id[:8]}`` and checks
        it out into ``data/worktrees/{session_id}/``.

        Returns the Worktree dataclass with the path to use as workspace_root.
        """
        git_root = await _find_git_root(workspace_root)
        if not git_root:
            raise RuntimeError(f"No git repository found at or above: {workspace_root}")

        wt_id = str(uuid.uuid4())[:8]
        branch = f"{branch_prefix}/{session_id[:8]}-{wt_id}"
        wt_path = _DATA_DIR / "worktrees" / session_id
        wt_path.parent.mkdir(parents=True, exist_ok=True)

        # Create worktree on a new branch based on HEAD
        await _run_git("worktree", "add", "-b", branch, str(wt_path), "HEAD", cwd=git_root)

        worktree = Worktree(
            id=wt_id,
            session_id=session_id,
            branch=branch,
            path=wt_path,
            git_root=git_root,
        )
        self._worktrees[session_id] = worktree
        return worktree

    async def get(self, session_id: str) -> Worktree | None:
        return self._worktrees.get(session_id)

    async def list(self) -> list[Worktree]:
        return list(self._worktrees.values())

    async def cleanup(self, session_id: str) -> bool:
        """Remove the worktree and delete the associated branch."""
        worktree = self._worktrees.pop(session_id, None)
        if not worktree:
            return False

        # Remove worktree registration from git
        await _run_git("worktree", "remove", "--force", str(worktree.path), cwd=worktree.git_root, check=False)

        # Delete the branch
        await _run_git("branch", "-D", worktree.branch, cwd=worktree.git_root, check=False)

        # Remove directory if still present
        if worktree.path.exists():
            shutil.rmtree(worktree.path, ignore_errors=True)

        return True

    async def commit(self, session_id: str, message: str) -> str:
        """Stage all changes in the worktree and create a commit. Returns commit SHA."""
        worktree = self._worktrees.get(session_id)
        if not worktree:
            raise RuntimeError(f"No worktree for session {session_id}")

        await _run_git("add", "-A", cwd=worktree.path)
        await _run_git("commit", "-m", message, cwd=worktree.path)
        _, sha, _ = await _run_git("rev-parse", "HEAD", cwd=worktree.path)
        return sha

    async def diff(self, session_id: str) -> str:
        """Return unified diff of all changes in the worktree vs the base branch."""
        worktree = self._worktrees.get(session_id)
        if not worktree:
            raise RuntimeError(f"No worktree for session {session_id}")
        _, out, _ = await _run_git("diff", "HEAD", cwd=worktree.path, check=False)
        return out

    async def merge_into_main(
        self, session_id: str, target_branch: str = "main", mark_message: Callable[[str], str] | None = None
    ) -> str:
        """Merge the worktree branch into the target branch. Returns merge commit SHA.

        ``mark_message`` (optional) rewrites the commit messages this merge creates, e.g. to add the AI trailers.
        """
        worktree = self._worktrees.get(session_id)
        if not worktree:
            raise RuntimeError(f"No worktree for session {session_id}")
        mark = mark_message or (lambda message: message)

        # Commit any pending changes first
        await _run_git("add", "-A", cwd=worktree.path, check=False)
        rc, _, _ = await _run_git("diff", "--cached", "--quiet", cwd=worktree.path, check=False)
        if rc != 0:
            await _run_git("commit", "-m", mark(f"Agent session {session_id} changes"), cwd=worktree.path)

        # Switch to target in main repo and merge
        await _run_git("checkout", target_branch, cwd=worktree.git_root)
        await _run_git(
            "merge",
            "--no-ff",
            worktree.branch,
            "-m",
            mark(f"Merge agent/{session_id[:8]} into {target_branch}"),
            cwd=worktree.git_root,
        )
        _, sha, _ = await _run_git("rev-parse", "HEAD", cwd=worktree.git_root)
        return sha


# Global singleton
worktree_service = WorktreeService()
