"""Bounded one-shot process execution: at the deadline the whole process tree dies.

A command the platform runs (a Maven or Gradle build, an OpenRewrite run, a shell command)
starts in its own session, so it leads a new process group. At the deadline, or when the
awaiting task is cancelled (a sub-agent group timeout, a stopped turn), that whole group is
killed, not only the direct child:

* ``process.kill()`` reaches only the direct child. A wrapper script, a forked test JVM or any
  other descendant keeps running and keeps the stdout/stderr pipes open.
* asyncio's ``Process.wait()`` and ``communicate()`` return only once every pipe is closed, so
  an unbounded ``await process.communicate()`` after the kill waits on those descendants.
* A cancelled ``wait_for`` raises ``CancelledError``, not ``TimeoutError``: without its own
  handler the process is never killed at all and runs on unsupervised.

After the kill the exit is awaited for a bounded grace period only. The result of a killed
run is the closed fact ``timed_out``; its partial output is not kept.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# How long the exit of a killed process group is awaited before the run is reported anyway.
KILL_EXIT_GRACE_SEC = 5.0


@dataclass(frozen=True)
class BoundedOutput:
    stdout: bytes
    stderr: bytes
    timed_out: bool


def process_group_spawn_kwargs() -> dict[str, Any]:
    """Keyword arguments that start a child as the leader of its own process group."""
    return {"start_new_session": True} if os.name == "posix" else {}


def kill_process_tree(process: Any, *, sig: int = signal.SIGKILL) -> None:
    """Signal the process group the child leads (SIGKILL by default); the child alone where there is none."""
    pid = getattr(process, "pid", None)
    if os.name == "posix" and isinstance(pid, int) and pid > 0:
        try:
            # The group outlives its leader: descendants are reached even after the child exited.
            os.killpg(pid, sig)
            return
        except OSError:
            # No group with that id: the child was spawned without a new session.
            pass
    try:
        if sig == signal.SIGKILL:
            process.kill()
        else:
            process.send_signal(sig)
    except ProcessLookupError:
        pass


async def _await_exit(process: Any, *, grace_sec: float) -> None:
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_sec)
    except TimeoutError:
        # A descendant that left the group still holds a pipe; the run is reported regardless.
        pass


async def communicate_within_deadline(
    process: Any,
    *,
    timeout_sec: float,
    on_kill: Callable[[], Awaitable[None]] | None = None,
    grace_sec: float = KILL_EXIT_GRACE_SEC,
) -> BoundedOutput:
    """``process.communicate()`` bounded by ``timeout_sec``; the tree dies at the deadline or on cancel.

    ``on_kill`` releases what the process group does not contain (a container behind a
    ``docker run`` client); it runs on both the deadline and the cancellation path.
    """
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
    except TimeoutError:
        kill_process_tree(process)
        if on_kill is not None:
            await on_kill()
        await _await_exit(process, grace_sec=grace_sec)
        return BoundedOutput(stdout=b"", stderr=b"", timed_out=True)
    except asyncio.CancelledError:
        kill_process_tree(process)
        if on_kill is not None:
            await on_kill()
        raise
    return BoundedOutput(stdout=stdout or b"", stderr=stderr or b"", timed_out=False)


__all__ = [
    "KILL_EXIT_GRACE_SEC",
    "BoundedOutput",
    "communicate_within_deadline",
    "kill_process_tree",
    "process_group_spawn_kwargs",
]
