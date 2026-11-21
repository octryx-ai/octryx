"""The launcher brings its pinned tools: a release archive is installed only when its sha256 is the
pinned one, into the launcher's own folder; a missing tool is a clear message; the device reports {id: version}."""

from __future__ import annotations

import hashlib
import io
import tarfile
import tomllib
from pathlib import Path

import pytest

from octryx_claude import tools, tools_data

GITLEAKS = next(item for item in tools_data.TOOLS if item["id"] == "gitleaks")


def _archive(script: str) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        body = script.encode()
        info = tarfile.TarInfo("gitleaks")
        info.size, info.mode = len(body), 0o755
        archive.addfile(info, io.BytesIO(body))
    return data.getvalue()


def test_the_pip_tools_are_pinned_alike_in_the_package_and_the_data():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    pins = dict(item.split("==", 1) for item in pyproject["project"]["dependencies"] if "==" in item)
    for tool in tools_data.TOOLS:
        if tool["source"] == "pip":
            assert pins[tool["package"]] == tool["version"], tool["id"]
    assert all(len(digest) == 64 for digest in GITLEAKS["sha256"].values())


def test_a_release_archive_is_installed_only_with_its_pinned_sha256(tmp_path, monkeypatch):
    archive = _archive(f"#!/bin/sh\necho 'gitleaks version {GITLEAKS['version']}'\n")
    platform_key = tools._platform()
    monkeypatch.setitem(GITLEAKS["sha256"], platform_key, hashlib.sha256(b"other").hexdigest())
    asked: list[str] = []

    def fetch(url: str, max_bytes: int) -> bytes:
        asked.append(url)
        return archive

    assert "does not match its pinned sha256" in tools._download(GITLEAKS, tmp_path, fetch)
    assert not (tmp_path / "tools" / "bin" / "gitleaks").exists()  # nothing installed
    assert asked[0].endswith(f"gitleaks_{GITLEAKS['version']}_{platform_key}.tar.gz")

    monkeypatch.setitem(GITLEAKS["sha256"], platform_key, hashlib.sha256(archive).hexdigest())
    assert tools._download(GITLEAKS, tmp_path, fetch) == ""
    assert tools._version_of(GITLEAKS, tmp_path) == GITLEAKS["version"]  # it answers the pinned version


def test_a_missing_tool_is_a_clear_message_and_offline_is_no_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_version_of", lambda tool, _root: None if tool["id"] in ("ast-grep", "gitleaks")
                        else tool["version"])

    def offline(_url: str, _max_bytes: int) -> bytes:
        raise OSError("network is unreachable")

    problems = tools.ensure(tmp_path, fetch=offline)
    assert any(item.startswith("ast-grep: missing from the launcher's environment") for item in problems)
    assert any(item.startswith("gitleaks: download failed (OSError") for item in problems)


def test_a_device_run_finds_the_tools_first_and_the_device_reports_them(tmp_path, monkeypatch):
    from octryx_claude import device_runtime
    from octryx_claude.pipeline_commands import _env

    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", str(tmp_path))
    path = _env(tmp_path, []).get("PATH", "").split(":")
    assert str(tmp_path / "tools" / "bin") in path[:3]
    monkeypatch.setattr(tools, "reported", lambda _root: {"ast-grep": "0.51.0", "gitleaks": None})
    monkeypatch.setattr(device_runtime.device_state, "load_device", lambda _state: {})
    monkeypatch.setattr(device_runtime, "seat_logged_in", lambda _state: False)
    monkeypatch.setattr(device_runtime.codex_seat, "reported_login", lambda _root: False)
    report = device_runtime.device_report(type("State", (), {"root": tmp_path})())
    assert report["tools"] == {"ast-grep": "0.51.0", "gitleaks": None}


@pytest.mark.parametrize("name", ["ast-grep", "playwright", "chromium", "gitleaks"])
def test_every_needed_tool_is_in_the_list(name):
    assert name in {tool["id"] for tool in tools_data.TOOLS}


def test_playwright_s_browsers_live_in_the_launcher_s_folder_never_in_home(tmp_path, monkeypatch):
    monkeypatch.delenv(tools.BROWSERS_ENV, raising=False)
    calls = []
    monkeypatch.setattr(tools, "_run", lambda command, timeout=30, env=None: (calls.append(env) or (1, "")))
    tools._browser_installed("chromium", tmp_path)
    assert calls[0] == {tools.BROWSERS_ENV: str(tmp_path / "tools" / "ms-playwright")}
    tools.use_own_browsers(tmp_path)
    import os

    assert os.environ[tools.BROWSERS_ENV] == str(tmp_path / "tools" / "ms-playwright")


def test_a_too_large_binary_is_refused_and_a_failed_write_leaves_nothing(tmp_path, monkeypatch):
    archive = _archive("#!/bin/sh\n" + "x" * 200)
    monkeypatch.setitem(GITLEAKS["sha256"], tools._platform(), hashlib.sha256(archive).hexdigest())
    monkeypatch.setitem(GITLEAKS, "max_bytes", 100)
    assert "larger than 100 bytes" in tools._download(GITLEAKS, tmp_path, lambda url, max_bytes: archive)
    folder = tmp_path / "tools" / "bin"
    assert list(folder.iterdir()) == []

    monkeypatch.setitem(GITLEAKS, "max_bytes", 10_000)

    def refuse(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", refuse)
    assert "disk full" in tools._download(GITLEAKS, tmp_path, lambda url, max_bytes: archive)
    assert list(folder.iterdir()) == []  # no .gitleaks.* left behind


def test_a_raw_release_binary_is_installed_under_its_release_name_with_its_sha256(tmp_path, monkeypatch):
    tool = next(item for item in tools_data.TOOLS if item["id"] == "osv-scanner")
    program = f"#!/bin/sh\necho 'osv-scanner version: {tool['version']}'\n".encode()
    platform_key = tools._platform()
    monkeypatch.setitem(tool["sha256"], platform_key, hashlib.sha256(program).hexdigest())
    asked: list[str] = []
    assert tools._download(tool, tmp_path, lambda url, max_bytes: asked.append(url) or program) == ""
    assert asked[0].endswith(f"osv-scanner_{tool['platforms'][platform_key]}")
    assert tools._version_of(tool, tmp_path) == tool["version"]
    assert {item["id"] for item in tools_data.TOOLS} >= {"opengrep", "osv-scanner"}
