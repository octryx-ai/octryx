"""Where this copy of octryx-claude runs from: a repository checkout or an installed package.

Claude Code calls the launcher back (hooks, ``apiKeyHelper``, MCP ``headersHelper``) through one
executable path, the *shim*. In a checkout that is ``clients/octryx-claude/bin/octryx-claude``; in an
installed copy it is the console script of the package's own venv (``venvs/<version>/bin/octryx-claude``),
so a running session keeps calling the exact version it started with even after an update switched
``venvs/current``.
"""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

DISTRIBUTION = "octryx-claude"
CHECKOUT_SHIM = Path(__file__).resolve().parents[1] / "bin" / "octryx-claude"


def installed_version() -> str:
    """The installed distribution's version (``0.2.0+<source hash>``), or ``""`` in a checkout."""
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return ""


def venv_shim(executable: str | None = None) -> Path:
    """The console script next to the interpreter, with ``venvs/current`` resolved to its version."""
    return Path(executable or sys.executable).parent.resolve() / "octryx-claude"


def launcher_shim(*, checkout_shim: Path = CHECKOUT_SHIM, executable: str | None = None) -> Path:
    """The executable Claude Code calls back. A checkout wins; otherwise the installed venv's script."""
    return checkout_shim if checkout_shim.is_file() else venv_shim(executable)
