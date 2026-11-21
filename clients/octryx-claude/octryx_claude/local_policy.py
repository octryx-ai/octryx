"""Where a session's local decision policy lives (``local_decisions``) and how it is read and written. Stdlib only.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from . import run_shell

POLICY_FILE = "local_policy.json"
CONTRACT_FILE = "workflow_run.json"  # run_contract.CONTRACT_FILE (not imported: it pulls in httpx)
HOME_ENV = "OCTRYX_CLAUDE_HOME"
SESSION_ENV = "OCTRYX_SESSION_KEY"
DEFAULT_HOME = Path.home() / ".octryx" / "claude"


def session_dir(env: Any = None) -> Path | None:
    """The hook's session folder (``LocalState.session_dir`` without importing it), ``None`` without a session."""
    source = os.environ if env is None else env
    try:
        key = str(uuid.UUID(str(source.get(SESSION_ENV) or "")))
    except ValueError:
        return None
    home = Path(str(source.get(HOME_ENV) or "")) if source.get(HOME_ENV) else DEFAULT_HOME
    return home / "sessions" / key


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def load_policy(folder: Path | None) -> dict[str, Any] | None:
    """The session's local decision policy, ``None`` when this session decides nothing locally."""
    if folder is None:
        return None
    policy = _read_json(folder / POLICY_FILE)
    return policy if policy.get("root") else None


def write_policy(folder: Path, offered: dict[str, Any], *, root: str, state_root: str) -> dict[str, Any]:
    """The offer's ``local_decisions`` block plus what only the device knows (the repository folder, its own state
    folder), written private next to the session's other state."""
    policy = {
        "root": os.path.realpath(root),
        "state_root": str(state_root),
        "scm_hosts": sorted({str(host).lower() for host in offered.get("scm_hosts") or [] if str(host or "")}
                            | set(run_shell.DEFAULT_SCM_HOSTS)),
        "deny_patterns": [str(item) for item in offered.get("deny_patterns") or [] if isinstance(item, str)],
        "server_commands": [[str(word) for word in prefix] for prefix in offered.get("server_commands") or []
                            if isinstance(prefix, list) and prefix],
        "server_path_globs": [str(item) for item in offered.get("server_path_globs") or [] if item],
    }
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / POLICY_FILE
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(policy, handle)
    return policy
