"""One askpass script per provider and process user, written once; it holds no secret.

The script only reads the username and the token from the git process's environment, so one per provider serves
every GitHub or GitLab git call; it lives in a folder only the process user may enter and is rewritten when it is
missing or changed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_SCRIPT = ("#!/bin/sh\n"
           "case \"$1\" in\n"
           "*Username*) printf '%s\\n' \"${{OCTRYX_{name}_USERNAME:-{default}}}\" ;;\n"
           "*) printf '%s\\n' \"$OCTRYX_{name}_SECRET\" ;;\n"
           "esac\n")


def askpass_script(provider: str, default_username: str) -> Path:
    """The provider's askpass script (``GITHUB`` / ``GITLAB``), created on first use, never one per call."""
    folder = Path(tempfile.gettempdir()) / f"octryx-askpass-{os.getuid()}"
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    path = folder / f"{provider.lower()}.sh"
    content = _SCRIPT.format(name=provider.upper(), default=default_username)
    if not path.is_file() or path.read_text(encoding="utf-8") != content:
        partial = folder / f".{provider.lower()}.{os.getpid()}.tmp"
        partial.write_text(content, encoding="utf-8")
        partial.chmod(0o700)
        partial.replace(path)  # atomic: a concurrent git call never sees a half-written script
    return path


__all__ = ["askpass_script"]
