from __future__ import annotations

import pytest

from octryx_claude import hook_outputs, local_tests, local_tests_screens, local_tests_words
from tests.local_tests_support import PHASE, SHIM, _hook_input

# ---- the repository's declared test command -----------

def _app(tmp_path, environment: dict) -> str:
    import json

    app = tmp_path / "coffee" / "flutter" / "claude" / ".octryx"
    app.mkdir(parents=True)
    (app / "environment.json").write_text(json.dumps(environment))
    return str(tmp_path)


@pytest.mark.parametrize("command", [
    "python -m playwright screenshot --viewport-size=1280,800 http://127.0.0.1:8765/ shots/home.png",
    ".venv/bin/python -m playwright screenshot --viewport-size 390,844 --full-page http://localhost:3000/menu m.png",
    "npx playwright screenshot http://[::1]:8000/?tab=week /repo/shots/week.png 2>&1 | tail -3",
])
def test_a_screenshot_of_the_local_app_runs_outside_the_sandbox(command):
    assert local_tests.is_test_run(command, "/repo")
    output = hook_outputs.test_run_output(_hook_input(command), PHASE, SHIM)
    assert local_tests.unwrap(output["hookSpecificOutput"]["updatedInput"]["command"]) == command


@pytest.mark.parametrize("command", [
    "python -m playwright screenshot https://example.com shot.png",  # loopback only
    "python -m playwright screenshot http://127.0.0.1.evil.test/ shot.png",
    "python -m playwright screenshot http://localhost@evil.test/ shot.png",
    "python -m playwright screenshot http://127.0.0.1:8765/ /Users/u/.ssh/shot.png",  # writes inside the repo only
    "python -m playwright screenshot --save-storage=s.json http://127.0.0.1:8765/ shot.png",
    "python -m playwright open http://127.0.0.1:8765/",
    "python -m playwright install chromium",
])
def test_other_playwright_commands_stay_in_the_sandbox(command):
    assert not local_tests.is_test_run(command, "/repo")


@pytest.mark.parametrize("command", [
    "python -m playwright screenshot http://127.0.0.1:24600/ shot.png",  # the platform's own port
    "python -m playwright screenshot http://localhost:24600/admin shot.png",
    "python -m playwright screenshot https://evil.test:8765/ shot.png",  # a foreign host
    "python -m playwright screenshot --user-data-dir=/Users/u/Chrome http://127.0.0.1:8765/ shot.png",
    "python -m playwright screenshot --load-storage=s.json http://127.0.0.1:8765/ shot.png",
])
def test_a_screenshot_never_looks_at_the_platform_or_a_foreign_host(command, monkeypatch):
    monkeypatch.setenv(local_tests_screens.PLATFORM_URL_ENV, "http://127.0.0.1:24600")
    assert not local_tests.is_test_run(command, "/repo")
    assert hook_outputs.test_run_output(_hook_input(command), PHASE, SHIM) is None
    assert local_tests.is_test_run("python -m playwright screenshot http://127.0.0.1:8765/ shot.png", "/repo")


def test_a_platform_elsewhere_leaves_every_loopback_port_to_the_app(monkeypatch):
    monkeypatch.setenv(local_tests_screens.PLATFORM_URL_ENV, "https://octryx.example.com")
    assert local_tests.is_test_run("python -m playwright screenshot http://127.0.0.1:443/ shot.png", "/repo")


def test_a_screenshot_outside_the_sandbox_is_stopped_at_its_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(local_tests, "SCREENSHOT_SECONDS", 1)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python"  # a "playwright" that hangs
    python.write_text("#!/bin/sh\nexec sleep 30\n")
    python.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.chdir(tmp_path)
    command = "python -m playwright screenshot http://127.0.0.1:8765/ shot.png"
    assert local_tests.takes_screenshot(command, str(tmp_path))
    assert not local_tests.takes_screenshot("python -m pytest -q", str(tmp_path))
    payload = local_tests_words.wrap("octryx-claude", command).split()[-1]
    assert local_tests.run_wrapped([payload]) == local_tests.DEADLINE_EXIT


def test_a_screenshot_may_first_make_its_folder_inside_the_repository():
    shot = "python3 -m playwright screenshot --viewport-size 1280,800 http://127.0.0.1:8811/ tests/system/shots/a.png"
    assert local_tests.is_test_run(f"mkdir -p tests/system/shots && {shot}", "/repo")
    assert local_tests.is_test_run(f"mkdir -p /repo/shots && {shot}", "/repo")
    assert not local_tests.is_test_run(f"mkdir -p /Users/u/.ssh/x && {shot}", "/repo")
    assert not local_tests.is_test_run(f"mkdir -p ../outside && {shot}", "/repo")
    assert not local_tests.is_test_run("mkdir -p tests/system/shots", "/repo")  # a mkdir alone is no test run


def test_the_declared_test_command_runs_outside_the_sandbox_like_pytest(tmp_path):
    from octryx_claude.local_tests_forms import is_test_run

    root = _app(tmp_path, {"test": "flutter test", "system_test": "python3 system_test/run_system_test.py"})
    assert is_test_run("flutter test", root)
    assert is_test_run("cd coffee/flutter/claude && flutter test test/grinder_default_test.dart 2>&1 | tail -40", root)
    assert is_test_run("flutter test --plain-name grind test/features/brews", root)
    assert is_test_run("python3 system_test/run_system_test.py", root)
    # Never more than the declared command: other commands, files outside, expansions, other subcommands.
    assert not is_test_run("flutter pub get", root)
    assert not is_test_run("flutter test /etc/passwd", root)
    assert not is_test_run("flutter test $HOME", root)
    assert not is_test_run("flutter test && rm -rf build", root)
    assert not is_test_run("flutter test", str(tmp_path / "elsewhere"))


def test_another_python_interpreter_runs_the_same_declared_script_outside_the_sandbox(tmp_path):
    from octryx_claude.local_tests_forms import is_test_run

    venv = _app(tmp_path / "a", {"system_test": ".venv/bin/python system_test/run_system_test.py"})
    plain = _app(tmp_path / "b", {"system_test": "python3 system_test/run_system_test.py"})
    for root in (venv, plain):
        for python in ("python", "python3", "python3.12", ".venv/bin/python", "app/.venv/bin/python3"):
            assert is_test_run(f"{python} system_test/run_system_test.py 2>&1 | tail -15", root), (root, python)
        # Only the interpreter word may differ: inline code, another script, an interpreter outside the repository.
        assert not is_test_run("python -c 'import os' system_test/run_system_test.py", root)
        assert not is_test_run("python system_test/other.py", root)
        assert not is_test_run("python -m http.server", root)
        assert not is_test_run("/tmp/x/bin/python system_test/run_system_test.py", root)
        assert not is_test_run("../venv/bin/python system_test/run_system_test.py", root)
        assert not is_test_run("node system_test/run_system_test.py", root)


def test_a_shell_or_inline_code_is_never_a_declared_test_command(tmp_path):
    from octryx_claude.local_tests_forms import is_test_run
    from octryx_claude.local_tests_words import declared_commands

    root = _app(tmp_path, {"test": "bash -c 'flutter test'", "system_test": "node -e 'run()'"})
    assert declared_commands(root) == []
    assert not is_test_run("bash -c x", root) and not is_test_run("node -e x", root)


def test_each_step_of_the_declared_lint_runs_outside_the_sandbox_like_the_tests(tmp_path):
    from octryx_claude.local_tests_forms import is_test_run

    lint = "dart format --output=none --set-exit-if-changed . && flutter analyze && dart run tool/check_lines.dart"
    root = _app(tmp_path, {"test": "flutter test", "lint": lint})
    assert is_test_run("flutter analyze", root)
    assert is_test_run("cd coffee/flutter/claude && flutter analyze 2>&1 | tail -5", root)
    assert is_test_run("dart run tool/check_lines.dart", root)
    assert is_test_run(f"cd coffee/flutter/claude && {lint}", root)
    assert not is_test_run("flutter analyze /etc", root)
    assert not is_test_run("dart run /tmp/x.dart", root)
    assert not is_test_run("flutter pub get", root)


def test_a_shell_in_the_declared_lint_is_never_run_outside(tmp_path):
    from octryx_claude.local_tests_words import declared_commands

    root = _app(tmp_path, {"lint": "flutter analyze && bash -c 'x' && node -e 'y'"})
    assert declared_commands(root) == [["flutter", "analyze"]]


def test_the_system_test_inside_a_longer_command_is_refused_at_once_with_the_form_that_runs():
    pinned = {"environment": {"test": "flutter test", "system_test": "python3 system_test/run_system_test.py"}}
    contract = {**PHASE, "environment_pin": pinned}
    compound = ("python3 - <<'EOF'\np='CHANGELOG.md'\nEOF\ndart format .; "
                "python3 system_test/run_system_test.py 2>&1 | tail -12")
    refused = hook_outputs.test_run_output(_hook_input(compound), contract, SHIM)
    reason = refused["hookSpecificOutput"]["permissionDecisionReason"]
    assert refused["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "run `python3 system_test/run_system_test.py 2>&1 | tail -15` as its own call" in reason
    alone_input = _hook_input("python3 system_test/run_system_test.py 2>&1 | tail -12")
    alone = hook_outputs.test_run_output(alone_input, contract, SHIM)
    assert alone["hookSpecificOutput"]["updatedInput"]["command"].startswith(f"{SHIM} test-run ")
    assert hook_outputs.test_run_output(_hook_input("dart format . && flutter analyze"), contract, SHIM) is None
