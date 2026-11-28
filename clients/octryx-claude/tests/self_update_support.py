"""Shared helpers for the test_self_update_* modules."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import httpx
import pytest

from octryx_claude import self_update, self_update_commands, self_update_layout
from octryx_claude.state import LocalState

from .conftest import BASE_URL

OLD, NEW = "0.2.0+aaaaaaaaaaaa", "0.2.0+bbbbbbbbbbbb"


WHEEL = b"PK fake wheel"


def _release(version: str = NEW, content: bytes = WHEEL) -> dict:
    return {"client": "octryx-claude", "version": version, "filename": f"octryx_claude-{version}-py3-none-any.whl",
            "sha256": hashlib.sha256(content).hexdigest()}


class Platform:
    def __init__(self, release: dict | Exception | httpx.Response, package: bytes = WHEEL) -> None:
        self.release, self.package, self.calls = release, package, []
        self.http = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if request.url.path.endswith("/version"):
            if isinstance(self.release, Exception):
                raise self.release
            if isinstance(self.release, httpx.Response):
                return self.release
            return httpx.Response(200, json=self.release)
        return httpx.Response(200, content=self.package)

    def version_calls(self) -> int:
        return sum(path.endswith("/version") for path in self.calls)


class Builder:
    def __init__(self, *, fail: bool = False, reports: str | None = None) -> None:
        self.fail, self.reports, self.argv = fail, reports, []

    def __call__(self, argv):
        argv = list(argv)
        self.argv.append(argv)
        if argv[-2:-1] == ["-c"]:  # the version probe
            return subprocess.CompletedProcess(argv, 0, stdout=f"{self.reports or Path(argv[0]).parents[1].name}\n")
        if self.fail:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="pip: no index")
        if "venv" in argv:
            venv = Path(argv[-1])
            (venv / "bin").mkdir(parents=True, exist_ok=True)
            (venv / "bin" / "octryx-claude").write_text("#!/bin/sh\n")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


@pytest.fixture
def installed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "state"
    venvs = root / "venvs"
    for version in ("0.1.0+000000000000", OLD):
        (venvs / version / "bin").mkdir(parents=True)
        (venvs / version / "bin" / "octryx-claude").write_text("#!/bin/sh\n")
    (venvs / "current").symlink_to(OLD)
    shim = home / ".local" / "bin" / "octryx-claude"
    shim.parent.mkdir(parents=True)
    shim.write_text(f"#!/bin/sh\n{self_update_layout.SHIM_MARK}\nexec '{venvs / 'current'}/bin/octryx-claude' \"$@\"\n")
    monkeypatch.delenv(self_update.AUTO_UPDATE_ENV, raising=False)
    monkeypatch.delenv(self_update.REEXEC_GUARD_ENV, raising=False)
    monkeypatch.delenv(self_update_commands.PYTHON_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(self_update.shutil, "which", lambda name: None)
    monkeypatch.setattr(self_update, "wants_pet", lambda root, platform=None: False)  # the pet tests opt in
    state = LocalState(root).ensure()
    state.write_config({"base_url": BASE_URL})
    return {"state": state, "home": home, "venvs": venvs, "shim": shim, "prefix": str(venvs / "current")}


def _update(installed, platform, *, builder=None, now=1_000_000.0, env=None, warnings=None):
    lines = [] if warnings is None else warnings
    return self_update.update_if_available(
        installed["state"], warn=lines.append, http=platform.http, runner=builder or Builder(),
        env={} if env is None else env, now=now, installed=OLD, prefix=installed["prefix"], home=installed["home"])
