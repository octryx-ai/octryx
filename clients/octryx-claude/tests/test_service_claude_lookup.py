"""A background device service finds ``claude`` without the user's shell PATH (launchd starts with a minimal one)."""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

import pytest

from octryx_claude import device_service, launch


def _fake_claude(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "claude"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def test_claude_is_found_in_an_install_dir_when_path_lacks_it(tmp_path, monkeypatch):
    binary = _fake_claude(tmp_path / "brew" / "bin")
    monkeypatch.delenv("OCTRYX_CLAUDE_EXECUTABLE", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(launch, "CLAUDE_FALLBACK_DIRS", (str(tmp_path / "brew" / "bin"),))
    assert launch.resolve_claude() == str(binary)


def test_claude_not_found_anywhere_is_still_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("OCTRYX_CLAUDE_EXECUTABLE", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(launch, "CLAUDE_FALLBACK_DIRS", (str(tmp_path / "missing"),))
    with pytest.raises(launch.LaunchRefusedError):
        launch.resolve_claude()


def test_the_launch_agent_runs_with_the_enabling_users_path(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/opt/homebrew/bin", "/usr/bin", "/bin"]))
    plist = plistlib.loads(device_service.launchd_plist(Path("/s"), Path("/l")))
    assert plist["EnvironmentVariables"]["PATH"].startswith("/opt/homebrew/bin")
