"""The platform's own cache clone of a repository (``var/repos/<provider>/...``), shared by GitHub, GitLab and Bitbucket.

Two runs on the same repository could prepare the
same cache clone at once (index.lock, a checkout against a pull), and a clone whose base branch had diverged could
never be pulled fast-forward. The clone is the platform's, not a team's, so the platform heals it itself:

* ``cache_clone_lock`` serialises the whole clone/fetch/checkout/branch sequence per clone, across processes (the API
  and the worker both prepare), with ``flock`` on a lock file next to the clone.
* ``BASE_SYNC`` puts the base branch exactly on ``origin/<base>`` (``checkout -f -B``), whatever the local base
  branch holds; no ``pull``, which only added a way to fail before the hard reset.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

LOCK_TIMEOUT_SECONDS = 600.0
_POLL_SECONDS = 0.2


@asynccontextmanager
async def cache_clone_lock(repo_path: Path, *, timeout_sec: float = LOCK_TIMEOUT_SECONDS) -> AsyncIterator[None]:
    """Exclusive use of one cache clone; waits (without blocking the event loop) up to ``timeout_sec``."""
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(repo_path.parent / f".{repo_path.name}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + timeout_sec
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"cache clone {repo_path.name} stayed locked for {timeout_sec:.0f} s") from None
                await asyncio.sleep(_POLL_SECONDS)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def base_sync(base_branch: str) -> tuple[tuple[list[str], str], ...]:
    """Commands that put the clone's base branch exactly on the fetched remote base, discarding local leftovers."""
    return (
        (["git", "checkout", "-f", "-B", base_branch, f"origin/{base_branch}"], "git checkout base branch failed"),
        (["git", "clean", "-fd"], "git clean failed"),
    )


__all__ = ["LOCK_TIMEOUT_SECONDS", "base_sync", "cache_clone_lock"]
