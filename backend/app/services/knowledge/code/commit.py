"""The commit a checkout is on, read from ``.git`` without running git.

An impact list is only reproducible when it names the commit it was computed from. The Knowledge
module runs no subprocess, so the commit is resolved from the repository metadata itself:

1. ``.git`` as a directory, or as a ``gitdir:`` pointer file (a worktree);
2. ``HEAD``, either detached (a hash) or a ``ref:``;
3. the ref's loose file, then ``packed-refs``, then the worktree's common directory.

An unresolvable checkout answers ``None``, which the caller reports as an explicit "not a git
checkout" rather than a guessed commit.
"""

from __future__ import annotations

import re
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")


def _git_dir(root: Path) -> Path | None:
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir:"):
            candidate = Path(text.split(":", 1)[1].strip())
            candidate = candidate if candidate.is_absolute() else (root / candidate)
            return candidate.resolve() if candidate.is_dir() else None
    return None


def _ref(git_dir: Path, ref: str) -> str | None:
    common = git_dir
    commondir = git_dir / "commondir"
    if commondir.is_file():
        common = (git_dir / commondir.read_text(encoding="utf-8").strip()).resolve()
    for base in (git_dir, common):
        loose = base / ref
        if loose.is_file():
            value = loose.read_text(encoding="utf-8").strip()
            if _SHA.fullmatch(value):
                return value
        packed = base / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split(" ", 1)
                if len(parts) == 2 and parts[1].strip() == ref and _SHA.fullmatch(parts[0]):
                    return parts[0]
    return None


def checkout_commit(root: Path) -> str | None:
    """The 40-character commit ``root`` is checked out at, or ``None``."""
    git_dir = _git_dir(root)
    if git_dir is None:
        return None
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip() if (git_dir / "HEAD").is_file() else ""
    if _SHA.fullmatch(head):
        return head
    if head.startswith("ref:"):
        return _ref(git_dir, head.split(":", 1)[1].strip())
    return None


__all__ = ["checkout_commit"]
