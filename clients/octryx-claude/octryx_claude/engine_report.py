"""Which engines this device can run and whose seat it is logged in to, as the handshake reports them."""

from __future__ import annotations

import importlib.util
import os
import shutil

from . import codex_seat
from .codex_driver import CODEX_PATH_ENV
from .codex_driver import ENGINE as ENGINE_CODEX
from .engine_state import ENGINE_CLAUDE
from .launch_process import PROFILE_SEAT
from .profile_choice import CLAUDE_CREDENTIAL_FILE, SEAT_SESSION_MARKER
from .state import LocalState


def _codex_installed(environ: dict[str, str]) -> bool:
    path = environ.get(CODEX_PATH_ENV) or shutil.which("codex", path=environ.get("PATH")) or ""
    return bool(path) and os.access(path, os.X_OK)


def installed_engines(environ: dict[str, str] | None = None) -> list[str]:
    # Claude Code runs through the Agent SDK, which brings its own CLI; Codex is the person's own install.
    env = dict(os.environ) if environ is None else environ
    found = [ENGINE_CLAUDE] if importlib.util.find_spec("claude_agent_sdk") is not None else []
    return found + ([ENGINE_CODEX] if _codex_installed(env) else [])


def seat_engines(state: LocalState) -> list[str]:
    claude = (state.claude_config_dir_for(PROFILE_SEAT) / CLAUDE_CREDENTIAL_FILE).exists() or \
        (state.root / SEAT_SESSION_MARKER).exists()
    return ([ENGINE_CLAUDE] if claude else []) + ([ENGINE_CODEX] if codex_seat.reported_login(state.root) else [])


__all__ = ["installed_engines", "seat_engines"]
