"""The commands that build an update's venv (uv when present, else python -m venv and pip) and check it."""

from __future__ import annotations

import hashlib
import hmac
import shutil
import subprocess
import sys
from collections.abc import Callable, MutableMapping, Sequence
from pathlib import Path

import httpx

from . import update_check
from .self_update_layout import (
    UpdateError,
)

PYTHON_OVERRIDE_ENV = "OCTRYX_INSTALL_PYTHON"  # the installer's override, honoured the same way

DOWNLOAD_TIMEOUT_SECONDS = 120.0

BUILD_TIMEOUT_SECONDS = 600.0

MIN_PYTHON = ">=3.11"

PET_REQUIREMENT = "octryx-claude[pet] @ {url}"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]

def default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          timeout=BUILD_TIMEOUT_SECONDS, check=False)

def build_commands(venv: Path, wheel: Path, env: MutableMapping[str, str]) -> list[list[str]]:
    """``create_venv`` of install.sh: uv when present (or the installer's Python override), never a package cache."""
    python = venv / "bin" / "python"
    override = env.get(PYTHON_OVERRIDE_ENV, "").strip()
    uv = None if override else shutil.which("uv")
    if uv:
        return [[uv, "venv", "--quiet", "--no-cache", "--python", MIN_PYTHON, str(venv)],
                [uv, "pip", "install", "--quiet", "--no-cache", "--python", str(python), str(wheel)]]
    base = override or getattr(sys, "_base_executable", "") or sys.executable
    return [[base, "-m", "venv", str(venv)],
            [str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-cache-dir",
             str(wheel)]]

def pet_command(venv: Path, wheel: Path, env: MutableMapping[str, str]) -> list[str]:
    """The extra on top of a built venv, the same way ``build_commands`` installs (uv or pip, no cache)."""
    python = venv / "bin" / "python"
    requirement = PET_REQUIREMENT.format(url=wheel.resolve().as_uri())
    override = env.get(PYTHON_OVERRIDE_ENV, "").strip()
    uv = None if override else shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--quiet", "--no-cache", "--python", str(python), requirement]
    return [str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-cache-dir",
            requirement]

def pet_autostart_command(venv: Path) -> list[str]:
    """After the switch: the pet on (and restarted on the new version) unless the person turned it off; without the
    extra its login item goes (``pet autostart``)."""
    return [str(venv / "bin" / "octryx-claude"), "pet", "autostart", "--restart"]

def venv_version_command(venv: Path) -> list[str]:
    # -I: neither the cwd (a checkout next to it) nor PYTHON* variables may answer for the new venv. The device
    # service modules are imported too: a build whose service cannot even import is never switched to.
    return [str(venv / "bin" / "python"), "-I", "-c",
            "import octryx_claude.cli, octryx_claude.device_runtime, octryx_claude.device_channel, "
            "octryx_claude.device_jobs; from importlib.metadata import version; print(version('octryx-claude'))"]

def _run(runner: Runner, argv: Sequence[str]) -> subprocess.CompletedProcess | None:
    try:
        return runner(argv)
    except (OSError, subprocess.SubprocessError):
        return None

def _reports(runner: Runner, venv: Path, version: str) -> bool:
    if not (venv / "bin" / "octryx-claude").exists():
        return False
    done = _run(runner, venv_version_command(venv))
    return done is not None and done.returncode == 0 and (done.stdout or "").strip() == version

def download(http: httpx.Client, base_url: str, release: update_check.Release, target: Path) -> None:
    """The wheel, written only after its sha256 matched the published one."""
    try:
        response = http.get(f"{base_url}/octryx-claude/package/{release.version}", timeout=DOWNLOAD_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise UpdateError("download_failed") from exc
    if response.status_code != 200:
        raise UpdateError("download_failed")
    if not hmac.compare_digest(hashlib.sha256(response.content).hexdigest(), release.sha256):
        raise UpdateError("digest_mismatch")
    target.write_bytes(response.content)
