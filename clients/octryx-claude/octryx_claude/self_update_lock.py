"""The update lock: one process updates an installation at a time; another one leaves it alone."""

from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Iterator

from .self_update_layout import (
    Layout,
)

LOCK_NAME = ".update.lock"

@contextlib.contextmanager
def _update_lock(layout: Layout) -> Iterator[bool]:
    fd = os.open(str(layout.venvs / LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
