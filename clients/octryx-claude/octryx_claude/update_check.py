"""The platform's served client release and the update notice for an installed octryx-claude.

``served_release`` reads ``GET /octryx-claude/version`` (version, wheel name, sha256); ``self_update`` uses it to
update an installed copy on start. With the auto-update switched off (``OCTRYX_CLAUDE_AUTO_UPDATE=0``) an installed
copy only gets the notice here: at most once per ``CHECK_INTERVAL_SECONDS`` one line names the update command when
the served version differs. A checkout never checks, and any failure (offline, refused, malformed answer) is
silent: the notice never delays or blocks a command.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TextIO

import httpx

from .install_layout import installed_version
from .state import LocalState

CHECK_INTERVAL_SECONDS = 24 * 60 * 60
CHECK_TIMEOUT_SECONDS = 3.0
STAMP_NAME = ".update-check"
VERSION_PATH = "/octryx-claude/version"
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+_-]{0,63}$")
# The same shapes install.sh accepts.
_FILENAME = re.compile(r"^octryx_claude-[0-9A-Za-z.+_-]+-py3-none-any\.whl$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReleaseUnavailableError(Exception):
    """No usable release; ``code`` is fixed (``offline``, ``timeout``, ``refused_<status>``, ``malformed``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Release:
    version: str
    filename: str
    sha256: str


def update_command(base_url: str) -> str:
    return f"curl -fsSL '{base_url}/octryx-claude/install.sh' | bash -s -- update"


def _due(state: LocalState, now: float) -> bool:
    stamp = state.root / STAMP_NAME
    try:
        last = float(stamp.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        last = 0.0
    return now - last >= CHECK_INTERVAL_SECONDS


def _stamp(state: LocalState, now: float) -> None:
    state.ensure()
    (state.root / STAMP_NAME).write_text(f"{int(now)}\n", encoding="utf-8")


def served_version(http: httpx.Client, base_url: str) -> str:
    """The platform's client version, or ``""`` on any failure."""
    try:
        response = http.get(f"{base_url}{VERSION_PATH}", timeout=CHECK_TIMEOUT_SECONDS)
        payload = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return ""
    version = payload.get("version") if isinstance(payload, dict) else None
    return version if isinstance(version, str) and _VERSION.fullmatch(version) else ""


def served_release(http: httpx.Client, base_url: str, *, timeout: float = CHECK_TIMEOUT_SECONDS) -> Release:
    """The platform's release with its package name and checksum; raises ``ReleaseUnavailableError``."""
    try:
        response = http.get(f"{base_url}{VERSION_PATH}", timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ReleaseUnavailableError("timeout") from exc
    except httpx.HTTPError as exc:
        raise ReleaseUnavailableError("offline") from exc
    if response.status_code != 200:
        raise ReleaseUnavailableError(f"refused_{response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ReleaseUnavailableError("malformed") from exc
    if not isinstance(payload, dict):
        raise ReleaseUnavailableError("malformed")
    fields = [payload.get(key) for key in ("version", "filename", "sha256")]
    if not all(isinstance(field, str) for field in fields):
        raise ReleaseUnavailableError("malformed")
    version, filename, sha256 = fields
    if not (_VERSION.fullmatch(version) and _FILENAME.fullmatch(filename) and _SHA256.fullmatch(sha256)
            and filename == f"octryx_claude-{version}-py3-none-any.whl"):
        raise ReleaseUnavailableError("malformed")
    return Release(version, filename, sha256)


def notice(installed: str, served: str, base_url: str) -> str:
    if not installed or not served or installed == served:
        return ""
    return (f"octryx-claude: update available ({installed} -> {served}); run: {update_command(base_url)}\n")


def notify(out: TextIO, *, state: LocalState | None = None, now: float | None = None,
           http: httpx.Client | None = None, installed: str | None = None) -> None:
    try:
        mine = installed_version() if installed is None else installed
        if not mine:
            return
        state = state or LocalState()
        base_url = str(state.config().get("base_url") or "").rstrip("/")
        moment = time.time() if now is None else now
        if not base_url or not _due(state, moment):
            return
        _stamp(state, moment)
        if http is None:
            with httpx.Client() as client:
                served = served_version(client, base_url)
        else:
            served = served_version(http, base_url)
        line = notice(mine, served, base_url)
        if line:
            out.write(line)
            out.flush()
    except Exception:  # noqa: BLE001 - the notice is best effort and never stops a command
        return
