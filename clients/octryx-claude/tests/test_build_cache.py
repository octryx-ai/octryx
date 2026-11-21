"""A build the device already made for the same inputs is reused; a changed input builds again (rc3
flutter-bug c1b57069: the system test and the hands-on serve each ran `flutter build web`)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from octryx_claude import build_cache

SPEC = [{"tool": "flutter", "args": ["build", "web"], "ignore_args": ["--release"], "output": "build/web",
         "inputs": ["lib", "pubspec.lock"]}]


@pytest.fixture
def app(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    calls = tmp_path / "calls.txt"
    fake = tools / "flutter"  # writes build/web like the real one and counts its calls
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\nmkdir -p build/web\n'
                    'cat lib/main.dart > build/web/index.html\n', encoding="utf-8")
    fake.chmod(0o755)
    folder = tmp_path / "app"
    (folder / "lib").mkdir(parents=True)
    (folder / "lib/main.dart").write_text("void main() {}\n", encoding="utf-8")
    (folder / "pubspec.lock").write_text("packages: {}\n", encoding="utf-8")
    monkeypatch.setenv("OCTRYX_BUILD_CACHE_ROOT", str(tmp_path / "cache"))
    env = build_cache.shim_env({**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"}, SPEC)
    return folder, env, calls


def _build(folder: Path, env: dict[str, str], command: str = "flutter build web") -> subprocess.CompletedProcess:
    return subprocess.run(command, shell=True, cwd=folder, env=env, capture_output=True, text=True, check=False)


def _calls(calls: Path) -> int:
    return len(calls.read_text(encoding="utf-8").splitlines()) if calls.exists() else 0


def test_the_second_build_of_the_same_inputs_is_served_from_the_cache(app):
    folder, env, calls = app
    assert _build(folder, env).returncode == 0 and _calls(calls) == 1
    first = (folder / "build/web/index.html").stat().st_mtime
    (folder / "build").rename(folder / "gone")  # the next run's folder has no build yet
    again = _build(folder, env, "flutter build web --release && test -f build/web/index.html")
    assert again.returncode == 0 and "build cache: hit" in again.stdout and _calls(calls) == 1
    assert (folder / "build/web/index.html").read_text(encoding="utf-8") == "void main() {}\n"
    assert (folder / "build/web/index.html").stat().st_mtime >= first  # newer than the sources, like a build
    notes = build_cache.read_notes(folder)
    assert [note["result"] for note in notes] == ["miss", "hit"] and len(notes[0]["key"]) == 64
    assert build_cache.read_notes(folder) == []  # each note goes up once


def test_a_changed_input_or_another_command_runs_the_real_tool(app):
    folder, env, calls = app
    _build(folder, env)
    (folder / "lib/main.dart").write_text("void main() { print(1); }\n", encoding="utf-8")
    assert "hit" not in _build(folder, env).stdout and _calls(calls) == 2
    assert (folder / "build/web/index.html").read_text(encoding="utf-8").startswith("void main() { print")
    _build(folder, env, "flutter build apk")
    assert _calls(calls) == 3  # not a declared artifact: always the real tool
    assert [note["result"] for note in build_cache.read_notes(folder)] == ["miss", "miss"]


def test_the_cache_is_off_for_a_run_that_builds_from_scratch(tmp_path):
    env = {"PATH": os.environ["PATH"], "OCTRYX_NO_BUILD_CACHE": "1"}
    assert build_cache.shim_env(env, SPEC) == env
    assert build_cache.shim_env({"PATH": os.environ["PATH"]}, []) == {"PATH": os.environ["PATH"]}
    assert json.loads(json.dumps(SPEC)) == SPEC
