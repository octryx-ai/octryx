"""Local state of the octryx-claude launcher.

Everything lives under one private directory (default
``~/.octryx/claude``, override with ``OCTRYX_CLAUDE_HOME``):

- ``config.json``       base URL, Workspace, model aliases, optional work item
- ``credentials.json``  OAuth client id, refresh token, cached access tokens (0600)
- ``credentials.lock``  serializes refreshes: refresh tokens rotate on every use and a
                        replayed token revokes the whole grant, so two helpers must
                        never refresh at the same time
- ``device-credentials.json`` the device grant of ``device enable`` (D1), same format; used
                        when ``OCTRYX_CREDENTIAL_SET=device`` (the device service and its jobs)
- ``device.json`` / ``device-key.pem``  the device registration and its Ed25519 key (0600)
- ``claude-config/``    ``CLAUDE_CONFIG_DIR`` for octryx sessions only (governed profile)
- ``claude-config-seat/`` ``CLAUDE_CONFIG_DIR`` of the ``seat`` profile: the user's own
                        subscription login lives here only (Claude Code keys its credential store by
                        config dir), never in plain ``claude``'s login. ``OCTRYX_CLAUDE_SEAT_CONFIG_DIR``
                        names another instance's seat dir instead (local dev loop, see ``seat_config_dir``)
- ``sessions/<key>/``   generated settings, MCP config and hook state per launch

Nothing is ever written to ``~/.claude``; plain ``claude`` stays untouched.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HOME_ENV = "OCTRYX_CLAUDE_HOME"
# A second launcher instance (own OCTRYX_CLAUDE_HOME) may reuse the seat login of the first one, see seat_config_dir.
SEAT_CONFIG_ENV = "OCTRYX_CLAUDE_SEAT_CONFIG_DIR"
# Which credential file a process uses: unset is the user's login; ``device`` the device grant.
CREDENTIAL_SET_ENV = "OCTRYX_CREDENTIAL_SET"
CREDENTIAL_SET_DEVICE = "device"
_DIR_MODE = 0o700
_FILE_MODE = 0o600


def default_root() -> Path:
    override = os.environ.get(HOME_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".octryx" / "claude"


def seat_config_dir(root: Path) -> Path:
    """The seat profile's ``CLAUDE_CONFIG_DIR``: ``<root>/claude-config-seat``, or ``OCTRYX_CLAUDE_SEAT_CONFIG_DIR``.

    Claude Code keys its macOS keychain login by the exact ``CLAUDE_CONFIG_DIR`` string, so a second instance with
    its own state dir (or a symlink to the first one's seat dir) sees no login. In a local dev loop the
    first instance's ``claude-config-seat`` reports ``loggedIn: true``, the same dir reached through a symlink
    ``loggedIn: false``. Naming the first instance's dir verbatim lets a local device service run seat jobs on the
    person's existing subscription login, with no second browser login. The dir is used as it is, never created.
    """
    shared = os.environ.get(SEAT_CONFIG_ENV, "").strip()
    if shared:
        return Path(shared).expanduser()
    # A configured seat dir path is kept as written, and so its keychain login.
    kept = read_json(root / "config.json").get("seat_config_dir")
    if isinstance(kept, str) and kept and Path(kept).is_dir():
        return Path(kept)
    return _ensure_private_dir(root / "claude-config-seat")


def _ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
    os.chmod(path, _DIR_MODE)
    return path


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace ``path`` with ``payload``; the file is 0600 from birth."""
    _ensure_private_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, _FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


class LocalState:
    def __init__(self, root: Path | None = None, *, credential_set: str | None = None) -> None:
        self.root = (root or default_root()).expanduser().resolve()
        chosen = os.environ.get(CREDENTIAL_SET_ENV, "") if credential_set is None else credential_set
        self.credential_set = CREDENTIAL_SET_DEVICE if chosen == CREDENTIAL_SET_DEVICE else ""

    def with_credential_set(self, credential_set: str) -> LocalState:
        return LocalState(self.root, credential_set=credential_set)

    @property
    def _credential_prefix(self) -> str:
        return "device-" if self.credential_set == CREDENTIAL_SET_DEVICE else ""

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def credentials_path(self) -> Path:
        return self.root / f"{self._credential_prefix}credentials.json"

    @property
    def claude_config_dir(self) -> Path:
        return _ensure_private_dir(self.root / "claude-config")

    def claude_config_dir_for(self, profile: str) -> Path:
        """The profile's own ``CLAUDE_CONFIG_DIR``; ``seat`` keeps its subscription login apart."""
        if profile == "seat":
            return seat_config_dir(self.root)
        return self.claude_config_dir

    def first_use(self, marker: str) -> bool:
        """True exactly once per ``marker`` (a fixed name); the marker file holds nothing."""
        path = self.root / f".{marker}"
        if path.exists():
            return False
        self.ensure()
        path.touch(mode=_FILE_MODE)
        return True

    def ensure(self) -> LocalState:
        _ensure_private_dir(self.root)
        return self

    def config(self) -> dict[str, Any]:
        return read_json(self.config_path)

    def write_config(self, payload: dict[str, Any]) -> None:
        write_private_json(self.config_path, payload)

    def credentials(self) -> dict[str, Any]:
        return read_json(self.credentials_path)

    def write_credentials(self, payload: dict[str, Any]) -> None:
        write_private_json(self.credentials_path, payload)

    @contextlib.contextmanager
    def credentials_lock(self) -> Iterator[None]:
        self.ensure()
        import fcntl  # noqa: PLC0415 - POSIX only; the native Windows pet imports this module without locking

        fd = os.open(str(self.root / f"{self._credential_prefix}credentials.lock"), os.O_RDWR | os.O_CREAT, _FILE_MODE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def session_dir(self, session_key: str) -> Path:
        # The key is always a UUID; parsing it keeps path components safe.
        canonical = str(uuid.UUID(session_key))
        return _ensure_private_dir(self.root / "sessions" / canonical)
