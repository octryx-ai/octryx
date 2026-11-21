"""Process ownership of the local dev launcher: scripts/dev-process-ownership.sh.

Launch records, the fail-closed ownership check, the owned process-group stop, the readiness
check and the port diagnostics, driven through the sourced module. ``tests.dev_launcher_test_support``
describes how the harness keeps every signal on processes the test started.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.dev_launcher_test_support import (
    BASH,
    FOREIGN_START_TIME,
    Processes,
    alive,
    free_port,
    launch,
    make_checkout,
    pid_dir_entries,
    read_when_ready,
    require_port_free,
    requires_process_tools,
    run_launcher,
    start_time,
    stop,
    wait_until,
    write_pid_record,
)

pytestmark = requires_process_tools

NODE_SERVER = """
const fs = require("fs");
const server = require("net").createServer();
server.listen(0, "127.0.0.1", () => {
  fs.writeFileSync("port.txt.tmp", String(server.address().port));
  fs.renameSync("port.txt.tmp", "port.txt");
});
"""

# ps test double: fails like a broken ps when every word of $FAKE_PS_FAIL is one of its
# arguments, and runs the real ps otherwise.
FAKE_PS = """#!/bin/sh
if [ -n "${FAKE_PS_FAIL:-}" ]; then
  matched=1
  for word in $FAKE_PS_FAIL; do
    case " $* " in
      *" $word "*) ;;
      *) matched=0 ;;
    esac
  done
  if [ "$matched" = 1 ]; then
    echo "ps: simulated lookup failure" >&2
    exit 1
  fi
fi
exec "REAL_PS" "$@"
"""

# One failing lookup each (shell code run before the stop, expected reason). None of them proves
# anything about the recorded process.
FAILED_LOOKUPS = {
    "process list": ('FAKE_PS_FAIL="-A"', "could not tell whether PID"),
    "start time": ('FAKE_PS_FAIL="lstart="', "its start time could not be read"),
    "process group": ('FAKE_PS_FAIL="pgid="', "its process group could not be read"),
    "working directory": ("dev_process_cwd() { :; }", "its working directory could not be read"),
    "own process group": ('FAKE_PS_FAIL="pgid= $$"', "the process group of this shell could not be read"),
}


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    return make_checkout(tmp_path)


@pytest.fixture
def processes(checkout: Path) -> Iterator[Processes]:
    tracked = Processes(checkout / "programs")
    yield tracked
    tracked.cleanup()


def _fake_ps_path(checkout: Path) -> str:
    """PATH with the FAKE_PS test double in front of the real ps."""
    fake_bin = checkout / "fakebin"
    fake_bin.mkdir()
    fake_ps = fake_bin / "ps"
    fake_ps.write_text(FAKE_PS.replace("REAL_PS", str(shutil.which("ps"))), encoding="utf-8")
    fake_ps.chmod(0o755)
    return f"{fake_bin}{os.pathsep}{os.environ['PATH']}"


def test_launch_writes_plain_pid_file_and_launch_record(checkout: Path, processes: Processes) -> None:
    pid = launch(checkout, "backend", checkout / "backend", sys.executable, processes.program("sleeper.py"))
    processes.track(pid)

    assert (checkout / "pids" / "backend.pid").read_text() == f"{pid}\n"
    assert (checkout / "pids" / "backend.launch").read_text() == f"pid={pid}\nstart={start_time(pid)}\n"
    assert pid_dir_entries(checkout) == ["backend.launch", "backend.pid"]
    assert os.getpgid(pid) == pid


def test_launch_replaces_leftover_staging_files_instead_of_writing_through_them(
    checkout: Path, processes: Processes
) -> None:
    # An interrupted launch can leave pids/*.new behind; as symlinks they must not redirect writes.
    victim = checkout / "elsewhere" / "victim"
    victim.write_text("untouched\n")
    for staged in ("backend.pid.new", "backend.launch.new"):
        (checkout / "pids" / staged).symlink_to(victim)

    pid = launch(checkout, "backend", checkout / "backend", sys.executable, processes.program("sleeper.py"))
    processes.track(pid)

    assert victim.read_text() == "untouched\n"
    record = checkout / "pids" / "backend.launch"
    assert not record.is_symlink()
    assert record.read_text() == f"pid={pid}\nstart={start_time(pid)}\n"
    assert pid_dir_entries(checkout) == ["backend.launch", "backend.pid"]


def test_owned_service_is_stopped_with_its_whole_process_group(checkout: Path, processes: Processes) -> None:
    backend = checkout / "backend"
    port_file, child_file = checkout / "port", checkout / "child.pid"
    leader = launch(
        checkout,
        "backend",
        backend,
        sys.executable,
        processes.program("listener_parent.py"),
        processes.program("listener.py"),
        str(port_file),
        str(child_file),
    )
    processes.track(leader)
    port = int(read_when_ready(port_file))
    child = int(read_when_ready(child_file))
    processes.track(child)
    # The port is held by a group member, not by the recorded PID, as with npm -> vite.
    assert os.getpgid(child) == leader

    result = stop(checkout, "backend", backend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Backend stopped (was PID {leader})" in result.stdout
    # SIGTERM reached the listening child as well, so no SIGKILL was needed.
    assert "SIGKILL" not in result.stdout
    wait_until(lambda: not alive(leader) and not alive(child))
    assert pid_dir_entries(checkout) == []
    assert require_port_free(port).returncode == 0
    assert "no PID file, nothing to stop" in stop(checkout, "backend", backend).stdout


@pytest.mark.parametrize("timeout", ["10", "0"])
def test_owned_service_gets_its_sigterm_grace_period(checkout: Path, processes: Processes, timeout: str) -> None:
    backend = checkout / "backend"
    shutdown, ready = checkout / "shutdown", checkout / "ready"
    pid = launch(
        checkout, "backend", backend, sys.executable, processes.program("graceful.py"), str(shutdown), str(ready)
    )
    processes.track(pid)
    wait_until(ready.exists)

    result = stop(checkout, "backend", backend, timeout=timeout)

    assert result.returncode == 0, result.stdout + result.stderr
    assert shutdown.exists() and shutdown.read_text() == "clean shutdown"
    assert "SIGKILL" not in result.stdout
    assert f"Backend stopped (was PID {pid})" in result.stdout
    # "0" is no valid timeout: it is reported and replaced by the 10 s default, never by zero grace.
    rejected = "DEV_LAUNCHER_STOP_TIMEOUT must be a whole number of seconds from 1 to 300; using 10."
    assert (rejected in result.stdout) == (timeout == "0")


def test_owned_group_ignoring_sigterm_is_killed_after_the_timeout(checkout: Path, processes: Processes) -> None:
    # Leader and child both ignore SIGTERM, so only a SIGKILL to the whole group ends them.
    backend = checkout / "backend"
    ready, child_ready = checkout / "ready", checkout / "child-ready"
    pid = launch(
        checkout,
        "backend",
        backend,
        sys.executable,
        processes.program("sigterm_ignorer.py"),
        str(ready),
        str(child_ready),
    )
    processes.track(pid)
    child = int(read_when_ready(child_ready))
    processes.track(child)
    read_when_ready(ready)
    assert os.getpgid(child) == pid

    result = stop(checkout, "backend", backend, timeout="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "did not exit within 1s after SIGTERM; sending SIGKILL to its process group" in result.stdout
    assert f"Backend stopped (was PID {pid})" in result.stdout
    wait_until(lambda: not alive(pid) and not alive(child))


@pytest.mark.parametrize(
    ("value", "outcome"),
    [
        ("1", "accepted 1"),
        ("300", "accepted 300"),
        ("301", "rejected 10"),
        ("0", "rejected 10"),
        ("5s", "rejected 10"),
        # Unbounded, this overflowed the poll count into an effectively endless wait.
        ("99999999999999999999", "rejected 10"),
    ],
)
def test_stop_timeout_is_bounded(value: str, outcome: str) -> None:
    result = run_launcher(
        'if grace=$(dev_stop_timeout); then echo "accepted $grace"; else echo "rejected $grace"; fi',
        DEV_LAUNCHER_STOP_TIMEOUT=value,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == f"{outcome}\n"


def test_stale_pid_file_is_cleared_without_signalling(checkout: Path) -> None:
    backend = checkout / "backend"
    pid = launch(checkout, "backend", backend, sys.executable, "-c", "pass")
    wait_until(lambda: not alive(pid))

    result = stop(checkout, "backend", backend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PID {pid} is no longer running; removed the stale PID file" in result.stdout
    assert pid_dir_entries(checkout) == []


def test_pid_beyond_the_system_range_counts_as_gone(checkout: Path) -> None:
    # macOS `ps -p` answers "process id too large" for it, which must not read as a failed lookup.
    (checkout / "pids" / "backend.pid").write_text("999999999\n")

    result = stop(checkout, "backend", checkout / "backend")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PID 999999999 is no longer running" in result.stdout
    assert pid_dir_entries(checkout) == []


def test_reused_pid_is_left_running(checkout: Path, processes: Processes) -> None:
    # Same directory and its own process group, but a different start time than recorded.
    backend = checkout / "backend"
    stranger = processes.spawn("sleeper.py", cwd=backend)
    write_pid_record(checkout, "backend", stranger.pid, start=FOREIGN_START_TIME)

    result = stop(checkout, "backend", backend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PID {stranger.pid} from" in result.stdout
    assert "the PID now belongs to another process" in result.stdout
    assert stranger.poll() is None
    assert pid_dir_entries(checkout) == []


def test_launch_record_naming_another_pid_is_refused(checkout: Path, processes: Processes) -> None:
    # Start time, directory and group all match, but the record was written for another PID.
    backend = checkout / "backend"
    pid = launch(checkout, "backend", backend, sys.executable, processes.program("sleeper.py"))
    processes.track(pid)
    (checkout / "pids" / "backend.launch").write_text(f"pid={os.getpid()}\nstart={start_time(pid)}\n")

    result = stop(checkout, "backend", backend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "its launch record is incomplete or names another PID" in result.stdout
    assert alive(pid)
    assert pid_dir_entries(checkout) == []


def test_process_outside_the_service_directory_is_left_running(checkout: Path, processes: Processes) -> None:
    # A genuine launch record, but the process does not run in this checkout's backend directory.
    pid = launch(checkout, "backend", checkout / "elsewhere", sys.executable, processes.program("sleeper.py"))
    processes.track(pid)

    result = stop(checkout, "backend", checkout / "backend")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "left running because its working directory is" in result.stdout
    assert alive(pid)
    assert pid_dir_entries(checkout) == []


def test_service_directory_reached_through_a_symlink_still_matches(checkout: Path, processes: Processes) -> None:
    # The launchers derive the service directory from their own path, which may run through a
    # symlink, while lsof reports the physical directory: the check compares inodes, not strings.
    backend = checkout / "backend"
    linked = checkout / "linked-backend"
    linked.symlink_to(backend, target_is_directory=True)
    pid = launch(checkout, "backend", backend, sys.executable, processes.program("sleeper.py"))
    processes.track(pid)

    result = stop(checkout, "backend", linked)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Backend stopped (was PID {pid})" in result.stdout
    wait_until(lambda: not alive(pid))


def test_pid_file_without_launch_record_is_left_running(checkout: Path, processes: Processes) -> None:
    # A PID record without identity evidence: right directory, but nothing proves the process is ours.
    backend = checkout / "backend"
    unproven = processes.spawn("sleeper.py", cwd=backend)
    write_pid_record(checkout, "backend", unproven.pid, start=None)

    result = stop(checkout, "backend", backend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "there is no launch record for it" in result.stdout
    assert unproven.poll() is None
    assert pid_dir_entries(checkout) == []


def test_process_that_does_not_lead_its_group_is_left_running(checkout: Path, processes: Processes) -> None:
    backend = checkout / "backend"
    port_file, child_file = checkout / "port", checkout / "child.pid"
    parent = processes.spawn(
        "listener_parent.py", processes.program("listener.py"), str(port_file), str(child_file), cwd=backend
    )
    child = int(read_when_ready(child_file))
    processes.track(child)
    read_when_ready(port_file)
    write_pid_record(checkout, "backend", child, start=start_time(child))

    result = stop(checkout, "backend", backend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "it does not lead its own process group" in result.stdout
    assert alive(child)
    assert parent.poll() is None


# "1" matters most: signalling process group -1 would reach every process of the user.
# "4294967297" is 2**32 + 1, which a 32-bit pid_t would wrap to 1.
@pytest.mark.parametrize("content", ["", "abc", "0", "1", "-1", "007", "12 34", "1\n2", "4294967297"])
def test_malformed_pid_file_is_removed_without_signalling(checkout: Path, content: str) -> None:
    (checkout / "pids" / "backend.pid").write_text(content)

    result = stop(checkout, "backend", checkout / "backend")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "did not hold a valid PID; removed it without signalling anything" in result.stdout
    assert pid_dir_entries(checkout) == []


@pytest.mark.parametrize("lookup", list(FAILED_LOOKUPS))
def test_failed_lookup_keeps_the_records_for_a_later_stop(checkout: Path, processes: Processes, lookup: str) -> None:
    backend = checkout / "backend"
    pid = launch(checkout, "backend", backend, sys.executable, processes.program("sleeper.py"))
    processes.track(pid)
    records = {entry.name: entry.read_text() for entry in (checkout / "pids").iterdir()}
    fault, reason = FAILED_LOOKUPS[lookup]
    fake_ps = {"FAKE_PS_FAIL": "", "PATH": _fake_ps_path(checkout)}

    result = stop(checkout, "backend", backend, prelude=f"{fault}\nexport FAKE_PS_FAIL", **fake_ps)

    assert result.returncode == 1, result.stdout + result.stderr
    assert reason in result.stdout
    assert alive(pid)
    assert {entry.name: entry.read_text() for entry in (checkout / "pids").iterdir()} == records
    # Nothing was proven either way, so once lookups work the same records stop the server.
    retry = stop(checkout, "backend", backend)
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert f"Backend stopped (was PID {pid})" in retry.stdout
    assert pid_dir_entries(checkout) == []


def test_stop_from_inside_the_owned_process_group_is_refused(checkout: Path, processes: Processes) -> None:
    # The server itself runs the stop, as a dev-stop.sh started by a command the backend spawned
    # would: the group signal would also reach the shell that sends it.
    backend = checkout / "backend"
    go, outcome = checkout / "go", checkout / "outcome.json"
    stop_script = 'set -eu\nsource "$DEV_LAUNCHER_LIBRARY"\ndev_stop_owned Backend "$PID_FILE" "$WORK_DIR"'
    program = processes.program("self_stopper.py")
    pid = launch(checkout, "backend", backend, sys.executable, program, str(go), str(outcome), BASH, "-c", stop_script)
    processes.track(pid)
    go.touch()
    wait_until(lambda: outcome.exists() or not alive(pid))

    assert outcome.exists(), "the stop signalled the process group it runs in"
    inside = json.loads(outcome.read_text())
    assert inside["returncode"] == 1, inside["output"]
    assert "this shell runs inside its process group" in inside["output"]
    assert alive(pid)
    assert pid_dir_entries(checkout) == ["backend.launch", "backend.pid"]
    # From outside the group the same records stop the server.
    result = stop(checkout, "backend", backend)
    assert f"Backend stopped (was PID {pid})" in result.stdout


def test_readiness_check_trusts_only_the_launched_identity(checkout: Path, processes: Processes) -> None:
    running = 'dev_launched_process_running "$PID_FILE"'
    backend_pid_file = checkout / "pids" / "backend.pid"
    pid = launch(checkout, "backend", checkout / "backend", sys.executable, processes.program("sleeper.py"))
    processes.track(pid)
    assert run_launcher(running, PID_FILE=str(backend_pid_file)).returncode == 0

    # The same live PID with another recorded start time is a reused PID, not the launched server.
    write_pid_record(checkout, "backend", pid, start=FOREIGN_START_TIME)
    assert run_launcher(running, PID_FILE=str(backend_pid_file)).returncode == 1

    # A record written for another PID vouches for nothing, even with the right start time.
    (checkout / "pids" / "backend.launch").write_text(f"pid={os.getpid()}\nstart={start_time(pid)}\n")
    assert run_launcher(running, PID_FILE=str(backend_pid_file)).returncode == 1

    exited = launch(checkout, "frontend", checkout / "frontend" / "chat", sys.executable, "-c", "pass")
    wait_until(lambda: not alive(exited))
    assert run_launcher(running, PID_FILE=str(checkout / "pids" / "frontend.pid")).returncode == 1


def test_foreign_listener_fails_startup_and_keeps_running(checkout: Path, processes: Processes) -> None:
    port_file = checkout / "port"
    # Its command line carries a secret: the diagnostics name the program, never its arguments.
    foreign = processes.spawn(
        "listener.py", str(port_file), "--api-token=launcher-test-secret", cwd=checkout / "elsewhere"
    )
    port = int(read_when_ready(port_file))

    # This test process holds a client connection to the port; only the listener may be named.
    with socket.create_connection(("127.0.0.1", port), timeout=5):
        result = require_port_free(port)

    assert result.returncode == 1
    assert f"Port {port} (backend) is already in use by a process this launcher does not own" in result.stdout
    assert f"PID {foreign.pid} (user" in result.stdout
    assert "program:" in result.stdout
    assert "launcher-test-secret" not in result.stdout
    assert f"PID {os.getpid()} " not in result.stdout
    assert f"kill {foreign.pid})" in result.stdout
    assert "then rerun ./dev-start.sh" in result.stdout
    assert foreign.poll() is None
    socket.create_connection(("127.0.0.1", port), timeout=5).close()


def test_stop_leaves_foreign_listener_with_reused_pid_running(checkout: Path, processes: Processes) -> None:
    # A stale PID file can name an unrelated listener on a dev port.
    port_file = checkout / "port"
    foreign = processes.spawn("listener.py", str(port_file), cwd=checkout / "elsewhere")
    port = int(read_when_ready(port_file))
    write_pid_record(checkout, "backend", foreign.pid, start=FOREIGN_START_TIME)

    result = stop(checkout, "backend", checkout / "backend")
    report = run_launcher('dev_report_port_listeners "$PORT" backend', PORT=str(port))

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PID {foreign.pid} from" in result.stdout and "was left running" in result.stdout
    assert report.returncode == 0, report.stdout + report.stderr
    assert f"Port {port} (backend) is still in use. Left running:" in report.stdout
    assert f"PID {foreign.pid} (user" in report.stdout
    assert foreign.poll() is None


def test_free_port_passes_the_startup_check() -> None:
    result = require_port_free(free_port())

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


@pytest.mark.skipif(shutil.which("npm") is None or shutil.which("node") is None, reason="needs npm and node")
def test_npm_launched_frontend_is_stopped_with_its_listening_child(checkout: Path, processes: Processes) -> None:
    frontend = checkout / "frontend" / "chat"
    package = {"name": "launcher-test", "private": True, "scripts": {"dev": "node server.js"}}
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (frontend / "server.js").write_text(NODE_SERVER, encoding="utf-8")
    npm = launch(checkout, "frontend", frontend, "npm", "run", "dev", npm_config_update_notifier="false")
    processes.track(npm)
    port = int(read_when_ready(frontend / "port.txt"))
    listener = int(run_launcher('dev_port_listeners "$PORT"', PORT=str(port)).stdout.split()[0])
    processes.track(listener)
    assert listener != npm and os.getpgid(listener) == npm

    result = stop(checkout, "frontend", frontend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Frontend stopped (was PID {npm})" in result.stdout
    wait_until(lambda: not alive(npm) and not alive(listener))
    assert require_port_free(port).returncode == 0
