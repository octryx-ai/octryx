from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

from octryx_claude import turn_processes


def _server(env: dict[str, str]) -> tuple[subprocess.Popen, int]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with socket.socket() as client:
            if client.connect_ex(("127.0.0.1", port)) == 0:
                return process, port
        time.sleep(0.1)
    process.kill()
    raise AssertionError("server did not start")


def test_only_the_turns_own_listening_servers_are_stopped():
    mark = turn_processes.new_mark()
    ours, _ = _server({**os.environ, turn_processes.MARK_ENV: mark})
    other, _ = _server({**os.environ, turn_processes.MARK_ENV: turn_processes.new_mark()})
    unmarked, _ = _server({k: v for k, v in os.environ.items() if k != turn_processes.MARK_ENV})
    try:
        stopped = turn_processes.stop_leftovers(mark, grace=5)
        assert stopped == [ours.pid]
        assert ours.wait(timeout=10) is not None
        assert other.poll() is None and unmarked.poll() is None
    finally:
        for process in (ours, other, unmarked):
            process.kill()
            process.wait()


def test_no_mark_stops_nothing():
    assert turn_processes.stop_leftovers("", pids=lambda: [1], environment=lambda pid: "") == []


def test_a_mark_matches_whole_entries_only():
    env = f"PATH=/bin {turn_processes.MARK_ENV}=abc123 HOME=/x"
    assert turn_processes._carries(env, "abc123") and not turn_processes._carries(env, "abc")


def test_every_process_the_turn_end_stops_is_recorded_with_its_command(monkeypatch):
    import os
    import signal

    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)) if sig != 0 else
                        (_ for _ in ()).throw(ProcessLookupError()))
    monkeypatch.setattr(turn_processes, "command_of", lambda pid: f"dart compile-server {pid}")
    mark = "abcdef0123456789"
    recorded: list[dict] = []
    stopped = turn_processes.stop_leftovers(
        mark, pids=lambda: [4242, 4343], grace=0.1, record=recorded.append,
        environment=lambda pid: f"{turn_processes.MARK_ENV}={mark}" if pid == 4242 else "OTHER=1")
    assert stopped == [4242] and (4242, signal.SIGTERM) in sent
    assert recorded == [{"pid": 4242, "command": "dart compile-server 4242", "mark": "abcdef01", "signal": "SIGTERM"}]
