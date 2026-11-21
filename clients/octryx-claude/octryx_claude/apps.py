"""The apps of a repository that holds several (C2): each tracked ``.octryx/environment.json``
names one. The preparation report lists them; the platform keeps the list on the repository record, so a later run
chooses its app before any change exists (a bug's intake reads it)."""

from __future__ import annotations

import subprocess
from pathlib import Path

MAX_APPS = 50
PATTERNS = (".octryx/environment.json", "*/.octryx/environment.json")


def found_apps(root: Path) -> list[str]:
    """The tracked environment files under ``root``, sorted; ``[]`` when git cannot say."""
    try:
        done = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", *PATTERNS], capture_output=True,
                              timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0:
        return []
    return sorted({name for name in done.stdout.decode("utf-8", errors="replace").split("\0") if name})[:MAX_APPS]


__all__ = ["MAX_APPS", "found_apps"]
