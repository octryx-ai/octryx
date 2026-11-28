"""Where this copy runs from (checkout or installed package) and the shim Claude Code calls back.
The installed shim is the version's own venv script, so a running session keeps its version across updates."""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

DISTRIBUTION = "octryx-claude"
CHECKOUT_SHIM = Path(__file__).resolve().parents[1] / "bin" / "octryx-claude"


def installed_version() -> str:
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return ""


def venv_shim(executable: str | None = None) -> Path:
    return Path(executable or sys.executable).parent.resolve() / "octryx-claude"


def launcher_shim(*, checkout_shim: Path = CHECKOUT_SHIM, executable: str | None = None) -> Path:
    return checkout_shim if checkout_shim.is_file() else venv_shim(executable)
