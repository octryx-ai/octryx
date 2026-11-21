"""The pet's "Connect iPhone…": opens a terminal window running ``octryx-claude mobile pair``.

The pairing is confirmed in that terminal (the phone's number), so it always runs where a person answers:

- macOS: a ``connect-iphone.command`` file in the state directory, opened with ``open`` (Terminal runs it; no
  automation permission is needed);
- native Windows: a new console window running ``octryx-claude.cmd mobile pair`` (it forwards to WSL).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

COMMAND_FILE = "connect-iphone.command"
CREATE_NEW_CONSOLE = 0x00000010


def command_file(root: Path, shim: Path) -> Path:
    path = root / COMMAND_FILE
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nexec {shlex.quote(str(shim))} mobile pair\n", encoding="utf-8")
    path.chmod(0o700)
    return path


def open_pairing(root: Path, *, spawn: Callable[..., object] = subprocess.Popen, platform: str | None = None,
                 shim: Path | None = None) -> Sequence[str]:
    """Start the pairing terminal; returns the command it ran (for the tests)."""
    platform = platform or sys.platform
    if platform == "darwin":
        if shim is None:
            from ..device_service import service_shim  # noqa: PLC0415

            shim = service_shim()
        argv = ["open", str(command_file(root, shim))]
        spawn(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return argv
    if platform == "win32" or os.name == "nt":
        argv = ["cmd.exe", "/k", "octryx-claude.cmd", "mobile", "pair"]
        spawn(argv, creationflags=CREATE_NEW_CONSOLE)
        return argv
    return []


__all__ = ["COMMAND_FILE", "command_file", "open_pairing"]
