"""The supervisor: the launcher stays alive as claude's parent instead of exec-ing it.

It holds the session's hook key in memory (see ``signer``), spawns claude as a child
with inherited stdio in the same process group and exits with the child's exit code
(``128 + signum`` for a signal death).

Signals:

- SIGINT and SIGQUIT: the terminal delivers them to the whole foreground process group,
  so claude receives them itself; the supervisor ignores them. A no-op handler is used
  instead of ``SIG_IGN`` because an ignored disposition would be inherited by claude.
- SIGTERM and SIGHUP: forwarded to claude.
- Job control: SIGTSTP does not stop the supervisor directly. When claude stops
  (``waitpid`` with ``WUNTRACED``) the supervisor stops itself with SIGSTOP, so the
  shell sees the job as stopped; on resume it sends SIGCONT to claude.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import Any

_IGNORED = (signal.SIGINT, signal.SIGQUIT, signal.SIGTSTP)
_FORWARDED = (signal.SIGTERM, signal.SIGHUP)


def _ignore(signum: int, frame: Any) -> None:
    return None


def _install(child_pid: Callable[[], int | None]) -> dict[int, Any]:
    def forward(signum: int, frame: Any) -> None:
        pid = child_pid()
        if pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signum)

    previous: dict[int, Any] = {}
    for signum in _IGNORED:
        previous[signum] = signal.signal(signum, _ignore)
    for signum in _FORWARDED:
        previous[signum] = signal.signal(signum, forward)
    return previous


def _restore(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        with contextlib.suppress(OSError, ValueError, TypeError):
            signal.signal(signum, handler)


def _exit_code(status: int) -> int:
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    return 1


def _wait(child: subprocess.Popen[bytes]) -> int:
    while True:
        try:
            _, status = os.waitpid(child.pid, os.WUNTRACED)
        except ChildProcessError:
            return 1
        if os.WIFSTOPPED(status):
            os.kill(os.getpid(), signal.SIGSTOP)
            # Resumed (the shell's SIGCONT reached the supervisor): wake claude too.
            with contextlib.suppress(ProcessLookupError):
                os.kill(child.pid, signal.SIGCONT)
            continue
        code = _exit_code(status)
        child.returncode = code
        return code


def supervise(argv: Sequence[str], env: Mapping[str, str]) -> int:
    """Run claude as a child and return its exit code. Raises ``OSError`` if it cannot start."""
    holder: dict[str, int] = {}
    previous = _install(lambda: holder.get("pid"))
    try:
        child = subprocess.Popen(list(argv), env=dict(env))
        holder["pid"] = child.pid
        return _wait(child)
    finally:
        _restore(previous)
