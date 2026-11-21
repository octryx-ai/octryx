"""The random identity of this platform process boot.

Every boot gets a fresh UUID, so a restarted process can never be mistaken for
the process that owned a turn before the restart. The identity is keyed by the
operating-system PID, so a forked child (a multi-worker server) gets its own
identity instead of inheriting its parent's.
"""

from __future__ import annotations

import os
import uuid

_identity: tuple[int, str] | None = None


def current_process_id() -> str:
    """This process boot's owner id (canonical UUID string)."""
    global _identity
    pid = os.getpid()
    if _identity is None or _identity[0] != pid:
        _identity = (pid, str(uuid.uuid4()))
    return _identity[1]


__all__ = ["current_process_id"]
