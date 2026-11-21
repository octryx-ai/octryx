"""Git-based workspace snapshot service.

Uses a separate --git-dir so it never interferes with the project's own git repo.
Snapshots are stored via `git write-tree` (no commits) so they are lightweight.
"""

from __future__ import annotations

import datetime
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..execution_runtime import execute_with_runtime

_DATA_DIR = Path(__file__).resolve().parents[4] / "data"
_PRUNE_DAYS = 7


@dataclass
class FileDiff:
    """Structured diff for a single file between two snapshots."""

    path: str
    status: str  # "added" | "deleted" | "modified"
    before: str | None = None
    after: str | None = None
    additions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "status": self.status,
            "before": self.before,
            "after": self.after,
            "additions": self.additions,
            "deletions": self.deletions,
        }


class SnapshotService:
    def __init__(self, session_id: str, worktree: str) -> None:
        self.git_dir = _DATA_DIR / "snapshots" / session_id
        self.worktree = Path(worktree).resolve()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _git(self, *args: str, check: bool = True) -> tuple[int, str, str]:
        cmd = [
            "git",
            f"--git-dir={self.git_dir}",
            f"--work-tree={self.worktree}",
            *args,
        ]
        result = await execute_with_runtime(
            db=None,
            project_config=None,
            command=cmd,
            cwd=self.worktree,
            workspace_root=self.worktree,
            timeout_sec=60,
            guard_foreign_build=False,  # the platform's own git (fixed subcommand), not an agent command
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        return_code = result.exit_code if result.exit_code is not None else 124
        if check and return_code not in (0, 1):  # 1 is ok for diff
            # Closed facts only: git output can carry credentialed remote URLs and internal paths.
            raise RuntimeError(f"git_command_failed subcommand={args[0]} exit_code={return_code}")
        return return_code, out, err

    # ── Public API ────────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Initialise the snapshot git dir if it doesn't exist yet.

        We create a non-bare repository whose GIT_DIR lives in data/snapshots/
        and whose work tree points at the user's workspace.  We cannot pass
        --bare here because that sets core.bare=true which then prevents any
        work-tree operations.  Instead we run `git init` with just --git-dir so
        that git creates the minimal .git structure without touching the
        worktree at all.
        """
        if not (self.git_dir / "HEAD").exists():
            self.git_dir.mkdir(parents=True, exist_ok=True)
            result = await execute_with_runtime(
                db=None,
                project_config=None,
                command=["git", f"--git-dir={self.git_dir}", "init"],
                cwd=self.worktree,
                workspace_root=self.worktree,
                timeout_sec=30,
                guard_foreign_build=False,  # the platform's own git (fixed subcommand), not an agent command
            )
            return_code = result.exit_code if result.exit_code is not None else 124
            if return_code not in (0, 1):
                raise RuntimeError("git init failed for snapshot repo")
            # Disable detached-worktree safety check added in recent git versions
            await self._git("config", "core.worktree", str(self.worktree), check=False)
            await self._git("config", "user.email", "snapshot@octryx", check=False)
            await self._git("config", "user.name", "Octryx Snapshot", check=False)

    async def track(self, label: str = "snapshot") -> str:
        """Stage all files and write a tree object. Returns the tree SHA."""
        # Stage everything under the worktree
        await self._git("add", "-A", check=True)
        _, sha, _ = await self._git("write-tree", check=True)
        if not sha:
            raise RuntimeError("git write-tree returned empty SHA")
        return sha

    async def restore(self, sha: str) -> None:
        """Overwrite the worktree with the state recorded in tree SHA.

        Steps:
        1. Read the snapshot tree into the index.
        2. Checkout the index into the worktree (restores modified/deleted files).
        3. Delete files that were added after the snapshot (not in the tree).
        """
        # 1. Stage current state so we can compute what was added
        await self._git("add", "-A", check=True)
        _, current_sha, _ = await self._git("write-tree", check=True)

        # 2. Find files that exist in current tree but NOT in the snapshot
        #    (diff-filter=A means "Added" relative to snapshot → delete them)
        _, added_files_out, _ = await self._git(
            "diff-tree",
            "--diff-filter=A",
            "--name-only",
            "-r",
            sha,
            current_sha,
            check=False,
        )
        files_to_delete = [f for f in added_files_out.splitlines() if f.strip()]

        # 3. Read the snapshot tree into the index
        await self._git("read-tree", sha, check=True)

        # 4. Checkout the index (restores snapshot files)
        await self._git("checkout-index", "-a", "-f", check=True)

        # 5. Delete files that were added after the snapshot
        for rel_path in files_to_delete:
            target = self.worktree / rel_path
            try:
                if target.exists():
                    target.unlink()
                    # Remove empty parent dirs up to worktree
                    parent = target.parent
                    while parent != self.worktree:
                        try:
                            parent.rmdir()  # only removes if empty
                        except OSError:
                            break
                        parent = parent.parent
            except Exception:
                pass

    async def diff(self, sha: str) -> str:
        """Return unified diff between tree SHA and current working tree."""
        # Stage current state first
        await self._git("add", "-A", check=True)
        _, current_sha, _ = await self._git("write-tree", check=True)
        _rc, out, _ = await self._git(
            "diff-tree",
            "--no-commit-id",
            "-r",
            "-p",
            sha,
            current_sha,
            check=False,
        )
        return out

    async def list_changed(self, sha: str) -> list[str]:
        """Return list of file paths changed since tree SHA."""
        await self._git("add", "-A", check=True)
        _, current_sha, _ = await self._git("write-tree", check=True)
        _, out, _ = await self._git("diff-tree", "--no-commit-id", "-r", "--name-only", sha, current_sha, check=False)
        return [line for line in out.splitlines() if line]

    async def diff_structured(self, sha: str) -> list[FileDiff]:
        """Return per-file structured diffs between tree SHA and current state."""
        await self._git("add", "-A", check=True)
        _, current_sha, _ = await self._git("write-tree", check=True)
        return await self._structured_diff(sha, current_sha)

    async def diff_range(self, sha_from: str, sha_to: str) -> list[FileDiff]:
        """Return per-file structured diffs between two tree SHAs."""
        return await self._structured_diff(sha_from, sha_to)

    async def _structured_diff(self, sha_from: str, sha_to: str) -> list[FileDiff]:
        """Internal: compute FileDiff list between two tree SHAs."""
        _, name_status_out, _ = await self._git(
            "diff-tree",
            "--no-commit-id",
            "-r",
            "--name-status",
            sha_from,
            sha_to,
            check=False,
        )
        _, patch_out, _ = await self._git(
            "diff-tree",
            "--no-commit-id",
            "-r",
            "-p",
            "--unified=0",
            sha_from,
            sha_to,
            check=False,
        )

        # Parse name-status to get file list + status
        status_map: dict[str, str] = {}
        for line in name_status_out.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                code, fpath = parts[0].strip(), parts[1].strip()
                if code.startswith("A"):
                    status_map[fpath] = "added"
                elif code.startswith("D"):
                    status_map[fpath] = "deleted"
                else:
                    status_map[fpath] = "modified"

        # Parse unified diff to extract before/after per file + line counts
        file_patches: dict[str, list[str]] = {}
        current_file: str | None = None
        for line in patch_out.splitlines(keepends=True):
            if line.startswith("diff --git"):
                # Extract b/filename
                parts = line.strip().split(" b/")
                current_file = parts[-1] if len(parts) > 1 else None
                if current_file and current_file not in file_patches:
                    file_patches[current_file] = []
            elif current_file is not None:
                file_patches[current_file].append(line)

        diffs: list[FileDiff] = []
        for fpath, status in status_map.items():
            patch_lines = file_patches.get(fpath, [])

            # Count additions/deletions from patch
            additions = sum(
                1 for patch_line in patch_lines if patch_line.startswith("+") and not patch_line.startswith("+++")
            )
            deletions = sum(
                1 for patch_line in patch_lines if patch_line.startswith("-") and not patch_line.startswith("---")
            )

            # Try to read before/after content from the trees
            before_content: str | None = None
            after_content: str | None = None
            try:
                if status in ("modified", "deleted"):
                    _, bc, _ = await self._git("cat-file", "-p", f"{sha_from}:{fpath}", check=False)
                    before_content = bc
                if status in ("modified", "added"):
                    _, ac, _ = await self._git("cat-file", "-p", f"{sha_to}:{fpath}", check=False)
                    after_content = ac
            except Exception:
                pass

            diffs.append(
                FileDiff(
                    path=fpath,
                    status=status,
                    before=before_content,
                    after=after_content,
                    additions=additions,
                    deletions=deletions,
                )
            )

        return diffs

    async def sync_gitignore(self) -> None:
        """Copy workspace .gitignore patterns into the snapshot repo's exclude file."""
        workspace_gitignore = self.worktree / ".gitignore"
        if not workspace_gitignore.exists():
            return
        exclude_dir = self.git_dir / "info"
        exclude_dir.mkdir(parents=True, exist_ok=True)
        exclude_file = exclude_dir / "exclude"
        patterns = workspace_gitignore.read_text(encoding="utf-8", errors="replace")
        # Prepend a header so we don't overwrite existing entries
        existing = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
        marker = "# --- synced from .gitignore ---\n"
        if marker in existing:
            # Replace the synced section
            before_marker = existing[: existing.index(marker)]
            exclude_file.write_text(before_marker + marker + patterns + "\n", encoding="utf-8")
        else:
            exclude_file.write_text(existing + "\n" + marker + patterns + "\n", encoding="utf-8")

    @staticmethod
    def prune_old_snapshots(max_age_days: int = _PRUNE_DAYS) -> list[str]:
        """Delete snapshot git dirs older than max_age_days. Returns list of pruned session_ids."""
        snapshots_dir = _DATA_DIR / "snapshots"
        if not snapshots_dir.exists():
            return []
        cutoff = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=max_age_days)
        pruned: list[str] = []
        for entry in snapshots_dir.iterdir():
            if not entry.is_dir():
                continue
            try:
                mtime = datetime.datetime.fromtimestamp(entry.stat().st_mtime, tz=datetime.UTC)
                if mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    pruned.append(entry.name)
            except Exception:
                pass
        return pruned
