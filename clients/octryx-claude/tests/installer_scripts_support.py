"""Shared installer paths and the PowerShell environment with a fake wsl.exe for the installer script tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
REPO = KIT.parents[1]
INSTALLER = KIT / "installer"
sys.path.insert(0, str(REPO / "backend" / "app" / "services"))

from octryx_client import installers  # noqa: E402

BASE_URL = "https://octryx.example.test"
PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="PowerShell (pwsh) not installed")


def _rendered_ps1(workspace: str = "") -> str:
    return installers.render((INSTALLER / "install.ps1").read_text(encoding="utf-8"), base_url=BASE_URL,
                             workspace=workspace)


# --- install.ps1: with pwsh --------------------------------------------------------------------

FAKE_WSL = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_WSL_LOG"
if [ "$1" = -d ]; then shift 2; fi
if [ "$1" = -e ]; then shift; fi
case "$1" in
  sh) [ -n "${FAKE_WSL_NO_DISTRO:-}" ] && exit 1
      printf 'Ubuntu\\n/home/tester\\n%s\\n' "${FAKE_WSL_KERNEL:-5.15.167.4-microsoft-standard-WSL2}" ;;
  bash) shift; exec bash "$@" ;;
  test) [ -z "${FAKE_WSL_NO_SHIM:-}" ] ;;
esac
"""


# Stands in for the platform download inside WSL: fails with FAKE_CURL_RC, else serves an install.sh
# stand-in that logs its arguments and exits with FAKE_WSL_BASH_RC.
FAKE_CURL = """#!/bin/sh
printf 'curl %s\\n' "$*" >> "$FAKE_WSL_LOG"
[ -n "${FAKE_CURL_RC:-}" ] && exit "$FAKE_CURL_RC"
printf 'printf "install.sh %%s\\\\n" "$*" >> "$FAKE_WSL_LOG"; exit %s\\n' "${FAKE_WSL_BASH_RC:-0}"
"""


@pytest.fixture
def ps_env(tmp_path):
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    wsl = fakebin / "wsl.exe"
    wsl.write_text(FAKE_WSL)
    wsl.chmod(0o755)
    curl = fakebin / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(0o755)
    script = tmp_path / "install.ps1"
    script.write_text(_rendered_ps1(), encoding="utf-8")
    env = {
        "PATH": f"{fakebin}:/usr/bin:/bin:{Path(PWSH).parent if PWSH else ''}",
        "HOME": str(tmp_path / "home"),
        "LOCALAPPDATA": str(tmp_path / "localappdata"),
        "FAKE_WSL_LOG": str(tmp_path / "wsl.log"),
        "TMPDIR": str(tmp_path),
    }
    (tmp_path / "home").mkdir()
    return tmp_path, script, env


def _pwsh(script: Path, env: dict, *args: str, extra: dict | None = None) -> subprocess.CompletedProcess:
    command = f"& ([scriptblock]::Create((Get-Content -Raw '{script}'))) {' '.join(args)}"
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
                          env={**env, **(extra or {})}, capture_output=True, text=True, timeout=120, check=False)
