"""Shared harness for the local dev launcher tests (dev-start.sh / dev-stop.sh)."""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LIBRARY = REPO_ROOT / "scripts" / "dev-process-ownership.sh"
LAUNCHERS = (REPO_ROOT / "dev-start.sh", REPO_ROOT / "dev-stop.sh")
BASH = "/bin/bash"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
# A start time no live process can have: the recorded process is gone and its PID was reused.
FOREIGN_START_TIME = "Thu Jan  1 00:00:00 1970"

requires_bash = pytest.mark.skipif(not Path(BASH).exists(), reason="the dev launcher needs /bin/bash")
requires_process_tools = pytest.mark.skipif(
    not Path(BASH).exists() or shutil.which("ps") is None or shutil.which("lsof") is None,
    reason="the dev launcher needs /bin/bash, ps and lsof",
)

PROGRAMS = {
    "sleeper.py": "import time\ntime.sleep(300)\n",
    "listener.py": (
        "import os, socket, sys, time\n"
        "server = socket.socket()\n"
        "server.bind(('127.0.0.1', 0))\n"
        "server.listen()\n"
        "with open(sys.argv[1] + '.tmp', 'w') as handle:\n"
        "    handle.write(str(server.getsockname()[1]))\n"
        "os.replace(sys.argv[1] + '.tmp', sys.argv[1])\n"
        "time.sleep(300)\n"
    ),
    # Shaped like npm -> vite and the uvicorn reloader -> worker: the leader spawns the listener.
    "listener_parent.py": (
        "import os, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "with open(sys.argv[3] + '.tmp', 'w') as handle:\n"
        "    handle.write(str(child.pid))\n"
        "os.replace(sys.argv[3] + '.tmp', sys.argv[3])\n"
        "time.sleep(300)\n"
    ),
    # Ignores SIGTERM. With a second ready file it first starts a child in its process group that
    # does the same. Each writes its PID to its ready file.
    "sigterm_ignorer.py": (
        "import os, signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "if len(sys.argv) > 2:\n"
        "    subprocess.Popen([sys.executable, sys.argv[0], sys.argv[2]])\n"
        "with open(sys.argv[1] + '.tmp', 'w') as handle:\n"
        "    handle.write(str(os.getpid()))\n"
        "os.replace(sys.argv[1] + '.tmp', sys.argv[1])\n"
        "time.sleep(300)\n"
    ),
    # Answers SIGTERM like a server that needs a moment to shut down cleanly.
    "graceful.py": (
        "import os, signal, sys, time\n"
        "def shut_down(signum, frame):\n"
        "    time.sleep(0.5)\n"
        "    with open(sys.argv[1] + '.tmp', 'w') as handle:\n"
        "        handle.write('clean shutdown')\n"
        "    os.replace(sys.argv[1] + '.tmp', sys.argv[1])\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, shut_down)\n"
        "open(sys.argv[2], 'w').close()\n"
        "time.sleep(300)\n"
    ),
    # Once the go file exists, runs a command inside its own process group (like a shell the dev
    # server spawns) and records how that command ended.
    "self_stopper.py": (
        "import json, os, subprocess, sys, time\n"
        "go_file, outcome_file, *command = sys.argv[1:]\n"
        "deadline = time.monotonic() + 60\n"
        "while not os.path.exists(go_file):\n"
        "    if time.monotonic() > deadline:\n"
        "        sys.exit(1)\n"
        "    time.sleep(0.05)\n"
        "done = subprocess.run(command, capture_output=True, text=True)\n"
        "with open(outcome_file + '.tmp', 'w') as handle:\n"
        "    json.dump({'returncode': done.returncode, 'output': done.stdout + done.stderr}, handle)\n"
        "os.replace(outcome_file + '.tmp', outcome_file)\n"
        "time.sleep(300)\n"
    ),
}


def start_time(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        env={**os.environ, "TZ": "UTC", "LC_ALL": "C"},
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def alive(pid: int) -> bool:
    return bool(start_time(pid))


def wait_until(condition: Callable[[], object], *, timeout: float = 60.0) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"condition not met within {timeout:.0f}s")


def read_when_ready(path: Path) -> str:
    return str(wait_until(lambda: path.exists() and path.read_text()))


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run_launcher(script: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [BASH, "-c", f'set -eu\nsource "$DEV_LAUNCHER_LIBRARY"\n{script}', "launcher-test", *args],
        env={**os.environ, "DEV_LAUNCHER_LIBRARY": str(LIBRARY), "DEV_LAUNCHER_TAG": "test", **env},
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        start_new_session=True,
    )
    return subprocess.CompletedProcess(result.args, result.returncode, strip_ansi(result.stdout), result.stderr)


class Processes:
    def __init__(self, programs: Path) -> None:
        self.programs = programs
        self._children: list[subprocess.Popen[bytes]] = []
        self._detached: list[tuple[int, str]] = []

    def program(self, name: str) -> str:
        return str(self.programs / name)

    def spawn(self, name: str, *args: str, cwd: Path) -> subprocess.Popen[bytes]:
        child = subprocess.Popen(
            [sys.executable, self.program(name), *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._children.append(child)
        return child

    def track(self, pid: int) -> None:
        self._detached.append((pid, start_time(pid)))

    def cleanup(self) -> None:
        for child in self._children:
            # An unreaped Popen child keeps its PID, so this cannot hit a reused PID.
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
        for pid, started in self._detached:
            if started and start_time(pid) == started:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def make_checkout(root: Path) -> Path:
    for relative in ("backend", "frontend/chat", "pids", "logs", "elsewhere", "programs"):
        (root / relative).mkdir(parents=True)
    for name, source in PROGRAMS.items():
        (root / "programs" / name).write_text(source, encoding="utf-8")
    return root


def pid_dir_entries(checkout: Path) -> list[str]:
    return sorted(entry.name for entry in (checkout / "pids").iterdir())


def launch(checkout: Path, service: str, work_dir: Path, *command: str, **env: str) -> int:
    pid_file = checkout / "pids" / f"{service}.pid"
    result = run_launcher(
        'dev_launch_detached "$PYTHON_BIN" "$WORK_DIR" "$PID_FILE" "$LOG_FILE" "$@"',
        *command,
        PYTHON_BIN=sys.executable,
        WORK_DIR=str(work_dir),
        PID_FILE=str(pid_file),
        LOG_FILE=str(checkout / "logs" / f"{service}.log"),
        **env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(pid_file.read_text())


def write_pid_record(checkout: Path, service: str, pid: int, *, start: str | None) -> None:
    (checkout / "pids" / f"{service}.pid").write_text(f"{pid}\n")
    if start is not None:
        (checkout / "pids" / f"{service}.launch").write_text(f"pid={pid}\nstart={start}\n")


def stop(
    checkout: Path, service: str, service_dir: Path, *, timeout: str = "5", prelude: str = "", **env: str
) -> subprocess.CompletedProcess[str]:
    return run_launcher(
        f'{prelude}\ndev_stop_owned "$LABEL" "$PID_FILE" "$SERVICE_DIR"',
        LABEL=service.capitalize(),
        PID_FILE=str(checkout / "pids" / f"{service}.pid"),
        SERVICE_DIR=str(service_dir),
        DEV_LAUNCHER_STOP_TIMEOUT=timeout,
        **env,
    )


def require_port_free(port: int) -> subprocess.CompletedProcess[str]:
    return run_launcher('dev_require_port_free "$PORT" backend', PORT=str(port))
