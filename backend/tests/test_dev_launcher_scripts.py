"""The local dev launcher scripts as shipped.

dev-stop.sh end to end, both launchers when the ownership module cannot be loaded, LF checkouts of
the shell scripts under core.autocrlf=true, and the ignored runtime pids/ directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.dev_launcher_test_support import (
    BASH,
    FOREIGN_START_TIME,
    LAUNCHERS,
    LIBRARY,
    REPO_ROOT,
    Processes,
    alive,
    free_port,
    launch,
    make_checkout,
    pid_dir_entries,
    read_when_ready,
    requires_bash,
    requires_process_tools,
    strip_ansi,
    wait_until,
    write_pid_record,
)

pytestmark = requires_bash
requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
requires_shellcheck = pytest.mark.skipif(shutil.which("shellcheck") is None, reason="needs shellcheck")
# The migration gate module and the explicit setup script as well.
SUPPORTING_SCRIPTS = (REPO_ROOT / "scripts" / "dev-migration-gate.sh", REPO_ROOT / "dev-setup.sh")
SHELL_SCRIPTS = (*LAUNCHERS, LIBRARY, *SUPPORTING_SCRIPTS)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    return make_checkout(tmp_path)


@pytest.fixture
def processes(checkout: Path) -> Iterator[Processes]:
    tracked = Processes(checkout / "programs")
    yield tracked
    tracked.cleanup()


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Runs git without the developer's global or system configuration."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=check)


def _clone_with_autocrlf(tmp_path: Path, name: str, files: tuple[Path, ...]) -> Path:
    """Commits ``files`` at their repository paths and returns a clone made with core.autocrlf=true."""
    source = tmp_path / f"{name}-source"
    for path in files:
        target = source / path.relative_to(REPO_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    _git(tmp_path, "init", "-q", str(source))
    _git(source, "add", "--all")
    _git(source, "-c", "user.name=launcher-test", "-c", "user.email=test@example.invalid", "commit", "-qm", "scripts")
    clone = tmp_path / f"{name}-clone"
    _git(tmp_path, "clone", "-q", "-c", "core.autocrlf=true", str(source), str(clone))
    return clone


@requires_process_tools
def test_dev_stop_script_stops_only_what_this_checkout_launched(checkout: Path, processes: Processes) -> None:
    # Runs a copy of the real dev-stop.sh inside the temporary checkout. Only the two dev port
    # literals are swapped for ephemeral ports, so the machine's real 8000/5173 are not inspected.
    port_file = checkout / "port"
    foreign = processes.spawn("listener.py", str(port_file), cwd=checkout / "elsewhere")
    foreign_port = int(read_when_ready(port_file))
    source = (REPO_ROOT / "dev-stop.sh").read_text(encoding="utf-8")
    backend_report = 'dev_report_port_listeners 8000 "backend"'
    frontend_report = 'dev_report_port_listeners 5173 "frontend"'
    assert backend_report in source and frontend_report in source
    source = source.replace(backend_report, f'dev_report_port_listeners {foreign_port} "backend"')
    source = source.replace(frontend_report, f'dev_report_port_listeners {free_port()} "frontend"')
    (checkout / "dev-stop.sh").write_text(source, encoding="utf-8")
    (checkout / "scripts").mkdir()
    shutil.copy(LIBRARY, checkout / "scripts" / LIBRARY.name)

    owned = launch(checkout, "backend", checkout / "backend", sys.executable, processes.program("sleeper.py"))
    processes.track(owned)
    stranger = processes.spawn("sleeper.py", cwd=checkout / "frontend" / "chat")
    write_pid_record(checkout, "frontend", stranger.pid, start=FOREIGN_START_TIME)

    result = subprocess.run(
        [BASH, str(checkout / "dev-stop.sh")],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        start_new_session=True,
    )
    output = strip_ansi(result.stdout)

    assert result.returncode == 0, output + result.stderr
    assert f"Backend stopped (was PID {owned})" in output
    assert f"Frontend: PID {stranger.pid} from" in output
    assert "the PID now belongs to another process" in output
    assert f"Port {foreign_port} (backend) is still in use" in output
    assert f"PID {foreign.pid} (user" in output
    wait_until(lambda: not alive(owned))
    assert stranger.poll() is None
    assert foreign.poll() is None
    assert pid_dir_entries(checkout) == []


@pytest.mark.parametrize("breakage", ["missing", "crlf"])
@pytest.mark.parametrize("launcher", LAUNCHERS, ids=lambda path: path.name)
def test_launcher_names_a_module_it_cannot_load(tmp_path: Path, launcher: Path, breakage: str) -> None:
    # dev-stop.sh reported a CRLF module as missing; dev-start.sh (set -e) exited without a word.
    shutil.copy(launcher, tmp_path / launcher.name)
    if breakage == "crlf":
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / LIBRARY.name).write_bytes(LIBRARY.read_bytes().replace(b"\n", b"\r\n"))

    result = subprocess.run(
        [BASH, str(tmp_path / launcher.name)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    output = strip_ansi(result.stdout + result.stderr)

    assert result.returncode == 1, output
    assert "Could not load scripts/dev-process-ownership.sh (see the error above)" in output
    assert "Missing" not in output
    assert "Stopping dev servers" not in output


@requires_shellcheck
def test_launcher_scripts_pass_shellcheck_without_waivers() -> None:
    # Every finding at every severity fails, and none may be waived: no `# shellcheck disable`
    # in the scripts, and --norc keeps any shellcheckrc out of the run.
    for script in SHELL_SCRIPTS:
        assert "shellcheck disable" not in script.read_text(encoding="utf-8"), script.name
    relative = [str(script.relative_to(REPO_ROOT)) for script in SHELL_SCRIPTS]
    result = subprocess.run(
        ["shellcheck", "--norc", "-x", *relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda path: path.name)
def test_launcher_scripts_parse(script: Path) -> None:
    result = subprocess.run([BASH, "-n", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_launchers_only_signal_through_the_ownership_library() -> None:
    for script in SHELL_SCRIPTS:
        source = script.read_text(encoding="utf-8")
        assert "kill -9" not in source
        assert "xargs kill" not in source
    for launcher in LAUNCHERS:
        source = launcher.read_text(encoding="utf-8")
        assert 'source "$SCRIPT_DIR/scripts/dev-process-ownership.sh"' in source
        assert "kill " not in source
    for script in SUPPORTING_SCRIPTS:
        # No kill, killall or pkill in any form: signalling stays in the ownership module.
        assert "kill" not in script.read_text(encoding="utf-8")


@requires_git
def test_shell_scripts_check_out_with_lf_under_autocrlf(tmp_path: Path) -> None:
    # core.autocrlf=true, a global setting on some developer machines, turns LF into CRLF on
    # checkout, and bash cannot run the result. The control clone without .gitattributes shows it.
    pinned = _clone_with_autocrlf(tmp_path, "pinned", (REPO_ROOT / ".gitattributes", *SHELL_SCRIPTS))
    control = _clone_with_autocrlf(tmp_path, "control", SHELL_SCRIPTS)

    for script in SHELL_SCRIPTS:
        relative = script.relative_to(REPO_ROOT)
        assert b"\r\n" in (control / relative).read_bytes(), relative
        checked_out = pinned / relative
        assert b"\r" not in checked_out.read_bytes(), relative
        parse = subprocess.run([BASH, "-n", str(checked_out)], capture_output=True, text=True, check=False)
        assert parse.returncode == 0, parse.stderr


@requires_git
def test_only_the_checkout_root_pids_directory_is_ignored(tmp_path: Path) -> None:
    # pids/ holds this checkout's launcher runtime state. A pids/ directory deeper in the tree (a
    # vendored snapshot, a package) stays visible, and .gitattributes is committed like any file.
    shutil.copyfile(REPO_ROOT / ".gitignore", tmp_path / ".gitignore")
    _git(tmp_path, "init", "-q")

    def ignored(path: str) -> bool:
        result = _git(tmp_path, "check-ignore", "--quiet", "--no-index", path, check=False)
        assert result.returncode in (0, 1), result.stderr
        return result.returncode == 0

    assert ignored("pids/backend.pid")
    assert ignored("pids/frontend.launch")
    assert not ignored("vendor/snapshot/pids/backend.pid")
    assert not ignored("backend/app/services/pids/policy.py")
    assert not ignored(".gitattributes")
