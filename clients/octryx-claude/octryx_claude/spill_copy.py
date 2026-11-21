"""The agent reads its own tool output that Claude Code moved into a file.

Claude Code writes a tool answer too long for the turn into ``<CLAUDE_CONFIG_DIR>/projects/<project>/<session>/
tool-results/<file>`` and tells the model to read it there. That folder lies under the launcher's state directory,
which the platform's self-protection, Claude Code's deny rules and the sandbox all keep away from the agent (it holds
the launcher's credentials). Nightly: 17 refused reads in 13 runs, each one the agent's own run contract.

The protection stays whole. Instead this hook copies exactly such a file into a folder of the session outside the
state directory and points the call at the copy (``updatedInput``), so the platform and Claude Code judge an ordinary
path. Only a regular file (no link) directly in a ``tool-results`` folder of this session's own transcript, under one
of the launcher's Claude config directories, is copied; a path with ``..`` or any other file of the state directory
is left alone and meets the protection.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

from .state import LocalState

COPY_ROOT = "octryx-tool-results"
FOLDER = "tool-results"
# A path that ends in ``.../projects/<project>/<session>/tool-results/<file>``, inside a command or alone.
_SPILLED = re.compile(r"(?P<path>/[^\s'\"<>|;&]*?/projects/[^/\s'\"]+/[^/\s'\"]+/tool-results/[A-Za-z0-9._-]+)")
PATH_TOOLS = {"Read": "file_path", "Grep": "path"}


def _config_projects(state: LocalState) -> list[Path]:
    from .state import seat_config_dir

    # The session's own CLAUDE_CONFIG_DIR first: Claude Code spills into exactly that folder, and the hook runs with
    # Claude Code's environment; the seat's config dir may come from OCTRYX_CLAUDE_SEAT_CONFIG_DIR (a shared keychain
    # login elsewhere), which the hook does not see, so <state>/claude-config-seat alone is not enough.
    own = os.environ.get("CLAUDE_CONFIG_DIR") or ""
    roots = {state.claude_config_dir, seat_config_dir(state.root), *([Path(own)] if own else [])}
    return [Path(os.path.realpath(root / "projects")) for root in roots]


def own_spill(state: LocalState, raw: str, session_id: str) -> Path | None:
    """``raw`` as this session's own spilled tool output, or ``None``."""
    if not raw or not session_id or ".." in raw.split("/"):
        return None
    path = Path(raw)
    if path.parent.name != FOLDER or path.parent.parent.name != session_id:
        return None
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    real = Path(os.path.realpath(path))
    if real.parent.name != FOLDER or real.parent.parent.name != session_id:
        return None  # a link on the way led elsewhere
    if any(real.parent.parent.parent.parent == base for base in _config_projects(state)):
        return real
    # Claude Code's own layout, whatever the hook's environment says: <config>/projects/<project>/<this session>/
    # tool-results/<file> beside the session's own transcript, also when the hook's environment names another config
    # dir (a person's own CLAUDE_CONFIG_DIR, a seat dir shared from elsewhere).
    session = real.parent.parent
    transcript = session.parent / f"{session_id}.jsonl"
    return real if session.parent.parent.name == "projects" and transcript.is_file() else None


def copy_folder(session_key: str) -> Path:
    folder = Path(tempfile.gettempdir()) / COPY_ROOT / session_key
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def _copied(state: LocalState, session_key: str, source: Path) -> str:
    target = copy_folder(session_key) / source.name
    shutil.copyfile(source, target)
    os.chmod(target, 0o600)
    return str(target)


def redirect(state: LocalState, session_key: str, hook_input: dict[str, Any]) -> dict[str, Any] | None:
    """The tool input pointed at copies of this session's spilled outputs, or ``None`` when it names none."""
    tool = str(hook_input.get("tool_name") or "")
    tool_input = hook_input.get("tool_input")
    session_id = str(hook_input.get("session_id") or "")
    if not isinstance(tool_input, dict):
        return None
    if tool in PATH_TOOLS:
        field = PATH_TOOLS[tool]
        source = own_spill(state, str(tool_input.get(field) or ""), session_id)
        return {**tool_input, field: _copied(state, session_key, source)} if source is not None else None
    if tool != "Bash":
        return None
    command = str(tool_input.get("command") or "")
    replaced = False

    def swap(match: re.Match[str]) -> str:
        nonlocal replaced
        source = own_spill(state, match.group("path"), session_id)
        if source is None:
            return match.group(0)
        replaced = True
        return _copied(state, session_key, source)

    rewritten = _SPILLED.sub(swap, command)
    return {**tool_input, "command": rewritten} if replaced else None


__all__ = ["COPY_ROOT", "copy_folder", "own_spill", "redirect"]
