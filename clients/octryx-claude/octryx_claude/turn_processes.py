"""App servers a run turn started stop when the turn ends; nothing the turn did not start is touched.

An app server or ``python -m http.server`` a session started would otherwise keep listening after its turn, holding
ports the next run's app wants.

Children of ``claude`` are re-parented once it exits, so neither the process tree nor a process group finds them
afterwards (Claude Code's Bash tool starts its own groups). What every one of them keeps is the environment: the
launcher gives each run turn a mark (:data:`MARK_ENV`, a fresh random value) and, after the turn, stops exactly the
processes that are still listening on a TCP port **and** carry this turn's mark. A process without it (another turn,
another session, anything the person started) is never signalled.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping

logger = logging.getLogger(__name__)

MARK_ENV = "OCTRYX_TURN_MARK"
GRACE_SECONDS = 5.0


def new_mark() -> str:
    return secrets.token_hex(16)


def listening_pids() -> set[int]:
    """Processes of this user listening on a TCP port (``lsof``; empty when it is missing)."""
    try:
        out = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fp"], capture_output=True, text=True,
                             timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(line[1:]) for line in out.splitlines() if line.startswith("p") and line[1:].isdigit()}


def environment_of(pid: int) -> str:
    """The process's environment as text (``/proc`` on Linux, ``ps -E`` on macOS); empty when unreadable."""
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/environ", "rb") as handle:
                return handle.read().replace(b"\0", b"\n").decode("utf-8", "replace")
        except OSError:
            return ""
    try:
        return subprocess.run(["ps", "-E", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _carries(environment: str, mark: str) -> bool:
    needle = f"{MARK_ENV}={mark}"
    return any(word == needle for word in environment.replace("\n", " ").split(" "))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def command_of(pid: int) -> str:
    """The process's command line (``ps``); empty when it is gone."""
    try:
        return subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=10, check=False).stdout.strip()[:300]
    except (OSError, subprocess.SubprocessError):
        return ""


def stop_leftovers(mark: str, *, pids: Callable[[], Iterable[int]] = listening_pids,
                   environment: Callable[[int], str] = environment_of, grace: float = GRACE_SECONDS,
                   record: Callable[[dict], object] | None = None) -> list[int]:
    """Stop the listening processes that carry ``mark`` (TERM, KILL after ``grace``); the pids it stopped. Each one
    is logged with its command and the turn's mark, and handed to ``record``, so every SIGTERM it sends is
    traceable."""
    if not mark:
        return []
    own = os.getpid()
    found = [pid for pid in pids() if pid != own and _carries(environment(pid), mark)]
    for pid in found:
        detail = {"pid": pid, "command": command_of(pid), "mark": mark[:8], "signal": "SIGTERM"}
        logger.warning("turn end: stopping pid %s (%s) with the turn's mark %s", pid, detail["command"], mark[:8])
        if record is not None:
            record(detail)
    for pid in found:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while any(_alive(pid) for pid in found) and time.monotonic() < deadline:
        time.sleep(0.1)
    for pid in found:
        if _alive(pid):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
    return found


def mark_of(env: Mapping[str, str]) -> str:
    return str(env.get(MARK_ENV) or "")


__all__ = ["MARK_ENV", "environment_of", "listening_pids", "mark_of", "new_mark", "stop_leftovers"]
