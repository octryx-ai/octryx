"""Bounded one-shot process execution: at the deadline the whole process tree dies."""

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
    return {"start_new_session": True} if os.name == "posix" else {}


def kill_process_tree(process: Any, *, sig: int = signal.SIGKILL) -> None:
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
