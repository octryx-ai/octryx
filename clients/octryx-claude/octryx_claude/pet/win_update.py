"""Self-update of the native Windows pet."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx

from .. import __version__, update_check

logger = logging.getLogger("octryx_claude.pet.update")

AUTO_UPDATE_ENV = "OCTRYX_CLAUDE_AUTO_UPDATE"
STATE_FILE = "pet-update.json"
CHECK_SECONDS = 6 * 3600.0
FAILED_RETRY_SECONDS = 3600.0
DOWNLOAD_TIMEOUT_SECONDS = 120.0
INSTALL_TIMEOUT_SECONDS = 300.0
CREATE_NO_WINDOW = 0x08000000

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=INSTALL_TIMEOUT_SECONDS, check=False,
                          stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)


def venv_python(executable: str | None = None) -> Path:
    current = Path(executable or sys.executable)
    candidate = current.with_name("python.exe")
    return candidate if candidate.exists() else current


def _read_state(root: Path) -> dict[str, Any]:
    try:
        data = json.loads((root / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(root: Path, **entries: Any) -> None:
    data = {**_read_state(root), **entries}
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / STATE_FILE).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        logger.warning("could not record the update state")


# The sha256 comes from the same server as the wheel, so TLS to the platform is the trust anchor.
def trusted_base_url(base_url: str) -> bool:
    lowered = base_url.strip().lower()
    if lowered.startswith("https://"):
        return True
    return any(lowered == prefix or lowered.startswith(prefix + "/") or lowered.startswith(prefix + ":")
               for prefix in ("http://localhost", "http://127.0.0.1"))


def update_once(account: Any, *, http: httpx.Client, runner: Runner = default_runner, now: float | None = None,
                installed: str = __version__, python: Path | None = None,
                env: dict[str, str] | None = None) -> str | None:
    source = os.environ if env is None else env
    if source.get(AUTO_UPDATE_ENV, "").strip().lower() in ("0", "off", "false", "no"):
        return None
    now = time.time() if now is None else now
    root = Path(account.root)
    base_url = account.base_url()
    if not base_url or not trusted_base_url(base_url):
        if base_url:
            logger.warning("pet updates need an https platform URL; %s is not one, so the pet keeps %s", base_url,
                           installed)
        return None
    _write_state(root, checked_at=now)
    try:
        release = update_check.served_release(http, base_url)
    except update_check.ReleaseUnavailableError as error:
        logger.info("no release to check (%s)", error.code)
        return None
    if release.version == installed:
        return None
    state = _read_state(root)
    failed_recently = now - float(state.get("failed_at") or 0) < FAILED_RETRY_SECONDS
    if state.get("failed_version") == release.version and failed_recently:
        return None
    python = python or venv_python()
    try:
        response = http.get(f"{base_url}/octryx-claude/package/{release.version}", timeout=DOWNLOAD_TIMEOUT_SECONDS)
        if response.status_code != 200:
            raise ValueError("download_failed")
        if not hmac.compare_digest(hashlib.sha256(response.content).hexdigest(), release.sha256):
            raise ValueError("digest_mismatch")
        with tempfile.TemporaryDirectory(prefix="octryx-pet-update-") as folder:
            wheel = Path(folder) / release.filename  # pip needs the wheel's own name
            wheel.write_bytes(response.content)
            # --no-deps: the running pet holds Pillow's and pystray's .pyd files, which Windows locks.
            installed_run = runner([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                                    "--no-deps", "--upgrade", str(wheel)])
            if installed_run.returncode != 0:
                raise ValueError("install_failed")
        probe = "import octryx_claude, octryx_claude.pet.tray; print(octryx_claude.__version__)"
        check = runner([str(python), "-c", probe])
        if check.returncode != 0 or (check.stdout or "").strip() != release.version:
            raise ValueError("check_failed")
    except (httpx.HTTPError, OSError, subprocess.SubprocessError, ValueError) as error:
        reason = str(error) if isinstance(error, ValueError) else type(error).__name__
        logger.warning("pet update to %s failed (%s); the pet keeps %s", release.version, reason, installed)
        _write_state(root, failed_version=release.version, failed_at=now, failed_reason=reason)
        return None
    _write_state(root, updated_to=release.version, updated_at=now)
    logger.info("pet updated %s -> %s", installed, release.version)
    return release.version


def watch(account: Any, stop: threading.Event, on_updated: Callable[[str], None], *,
          check: Callable[[], str | None] | None = None, interval: float = CHECK_SECONDS) -> None:
    def default_check() -> str | None:
        with httpx.Client(follow_redirects=False) as http:
            return update_once(account, http=http)

    run = check or default_check
    while not stop.is_set():
        try:
            version = run()
        except Exception:  # noqa: BLE001 - an update check never ends the pet
            logger.warning("pet update check failed", exc_info=True)
            version = None
        if version:
            on_updated(version)
            return
        stop.wait(interval)


__all__ = ["CHECK_SECONDS", "update_once", "watch"]
