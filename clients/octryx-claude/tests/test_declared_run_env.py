"""An agent's wrapped run of a declared command sees what the pipeline's run of it sees: the launcher's interpreter
first on ``PATH`` (a declared ``python3 system_test/run_system_test.py`` must not find ``/usr/bin/python3``, which has
no Playwright)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from octryx_claude import local_tests, local_tests_words, pipeline_commands, tools

SYSTEM_TEST = "python3 system_test/run_system_test.py"


def _app(tmp_path: Path, environment: dict) -> Path:
    (tmp_path / ".octryx").mkdir()
    (tmp_path / ".octryx" / "environment.json").write_text(json.dumps(environment))
    (tmp_path / "system_test").mkdir()
    (tmp_path / "system_test" / "run_system_test.py").write_text("import sys\nprint(sys.executable)\n")
    return tmp_path


@pytest.fixture
def system_python_first(tmp_path_factory, monkeypatch):
    """The device's ``PATH`` with a ``python3`` before the launcher's (as ``/usr/bin/python3`` on macOS)."""
    folder = tmp_path_factory.mktemp("system-bin")
    fake = folder / "python3"
    fake.write_text("#!/bin/sh\necho SYSTEM-PYTHON-WITHOUT-PLAYWRIGHT\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([str(folder), "/usr/bin", "/bin"]))
    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", str(tmp_path_factory.mktemp("state")))
    monkeypatch.delenv(tools.BROWSERS_ENV, raising=False)


def test_the_declared_system_test_runs_with_the_launchers_interpreter_like_the_pipeline(tmp_path,
                                                                                        system_python_first):
    app = _app(tmp_path, {"test": "flutter test", "system_test": SYSTEM_TEST, "browser": "chrome"})
    env = local_tests.declared_env(f"{SYSTEM_TEST} 2>&1 | tail -15", str(app))
    assert env is not None
    assert env["PATH"] == pipeline_commands._env(app, [], {"system_test": SYSTEM_TEST, "browser": "chrome"})["PATH"]
    assert env[tools.BROWSERS_ENV] == str(tools.browsers_path(tools.default_root()))
    done = subprocess.run(["/bin/sh", "-c", SYSTEM_TEST], cwd=app, env=env, capture_output=True, text=True,
                          check=True)
    assert "SYSTEM-PYTHON" not in done.stdout
    assert Path(done.stdout.strip()).parent == Path(sys.executable).parent


def test_other_commands_keep_the_sessions_environment(tmp_path, system_python_first):
    app = _app(tmp_path, {"system_test": SYSTEM_TEST})
    for command in ("python3 -m pytest -q", "python3 system_test/other.py", "flutter test"):
        assert local_tests.declared_env(command, str(app)) is None, command


def test_the_pinned_environment_decides_not_the_file_the_agent_may_have_rewritten(tmp_path, system_python_first):
    app = _app(tmp_path, {"system_test": "python3 evil.py", "path": ["/tmp/evil"]})
    pinned = {"environment": {"system_test": SYSTEM_TEST, "path": ["tool/bin"]}}
    env = local_tests.declared_env(SYSTEM_TEST, str(app), pinned)
    assert env is not None and env["PATH"].split(os.pathsep)[0] == str((app / "tool" / "bin").resolve())
    assert local_tests.declared_env("python3 evil.py", str(app), pinned) is None


def test_the_wrapper_hands_the_declared_run_the_pipelines_environment(tmp_path, system_python_first, monkeypatch):
    app = _app(tmp_path, {"system_test": SYSTEM_TEST})
    monkeypatch.delenv("OCTRYX_SESSION_KEY", raising=False)
    monkeypatch.chdir(app)
    seen: dict = {}

    def execve(_path, args, env):
        seen.update(args=args, env=env)
        raise SystemExit(0)

    monkeypatch.setattr(local_tests.os, "execve", execve)
    wrapped = local_tests_words.wrap("/Users/u/.local/bin/octryx-claude", f"{SYSTEM_TEST} | tail -5")
    with pytest.raises(SystemExit):
        local_tests.run_wrapped([wrapped.split()[-1]])
    assert seen["args"][-1].endswith(f"{SYSTEM_TEST} | tail -5")
    assert seen["env"]["PATH"].split(os.pathsep)[0] == str(Path(sys.executable).parent)
