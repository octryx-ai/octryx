"""The installer's layout under the state dir and switching its current venv."""

from __future__ import annotations

import contextlib
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

SHIM_MARK = "# octryx-claude shim (managed by the Octryx installer)"

class UpdateError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

@dataclass(frozen=True)
class Layout:
    root: Path
    home: Path

    @property
    def venvs(self) -> Path:
        return self.root / "venvs"

    @property
    def current(self) -> Path:
        return self.venvs / "current"

    @property
    def shim(self) -> Path:
        shim = self.home / ".local" / "bin" / "octryx-claude"
        try:
            text = shim.read_text(encoding="utf-8", errors="replace")
            # Only the shim of this installation: another OCTRYX_CLAUDE_HOME's shim runs another state.
            if SHIM_MARK in text and f"{self.current}/bin/octryx-claude" in text:
                return shim
        except OSError:
            pass
        return self.current / "bin" / "octryx-claude"

    def active(self) -> str:
        try:
            return os.readlink(self.current)
        except OSError:
            return ""

@dataclass(frozen=True)
class Updated:
    previous: str
    version: str
    layout: Layout

def switch(layout: Layout, version: str) -> str:
    previous = layout.active()
    staged = layout.venvs / f".current.{os.getpid()}"
    with contextlib.suppress(FileNotFoundError):
        staged.unlink()
    staged.symlink_to(version)
    os.replace(staged, layout.current)
    version_file = layout.root / "installed-version"
    tmp = version_file.with_name(f".installed-version.{os.getpid()}")
    tmp.write_text(f"{version}\n", encoding="utf-8")
    os.replace(tmp, version_file)
    return previous

def prune(layout: Layout, keep: Sequence[str]) -> None:
    for entry in layout.venvs.iterdir():
        if entry.name in keep or entry.name.startswith(".") or entry.is_symlink() or not entry.is_dir():
            continue
        shutil.rmtree(entry, ignore_errors=True)
