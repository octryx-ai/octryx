"""The random identity of this platform process boot."""

from __future__ import annotations

import os
import uuid

_identity: tuple[int, str] | None = None


def current_process_id() -> str:
    global _identity
    pid = os.getpid()
    if _identity is None or _identity[0] != pid:
        _identity = (pid, str(uuid.uuid4()))
    return _identity[1]


__all__ = ["current_process_id"]
