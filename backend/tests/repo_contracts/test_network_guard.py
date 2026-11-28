"""tests/support/network_guard.py keeps unit tests off the real network while fixture servers on this machine keep working."""

import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tests.support import network_guard
from tests.support.network_guard import NetworkAccessBlockedError

pytestmark = pytest.mark.skipif(network_guard.MODE != "block", reason="the guard is not in block mode")


def test_a_connection_to_another_machine_is_refused_with_a_clear_message():
    with pytest.raises(NetworkAccessBlockedError, match="must not reach the network: 93.184.215.14:443"):
        socket.create_connection(("93.184.215.14", 443), timeout=5)
    with socket.socket() as raw, pytest.raises(NetworkAccessBlockedError):
        raw.connect(("8.8.8.8", 53))


def test_a_name_lookup_for_another_machine_is_refused():
    with pytest.raises(NetworkAccessBlockedError, match="bitbucket.org"):
        socket.getaddrinfo("bitbucket.org", 443)


def test_a_fixture_server_on_this_machine_still_answers():
    class Ok(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's naming
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Ok)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with socket.create_connection(("localhost", server.server_port), timeout=5) as conn:
            conn.sendall(b"GET / HTTP/1.0\r\n\r\n")
            assert conn.recv(64).startswith(b"HTTP/1.0 204")
    finally:
        server.shutdown()


def test_git_toward_another_machine_fails_at_once_without_a_prompt(tmp_path):
    started = time.monotonic()
    result = subprocess.run(["git", "ls-remote", "https://bitbucket.org/acme/never-reached.git"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode != 0
    assert time.monotonic() - started < 15  # the closed proxy port refuses at once; no 120 s timeout, no askpass
    ssh = subprocess.run(["git", "ls-remote", "ssh://git@bitbucket.org/acme/never-reached.git"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=60, check=False)
    assert ssh.returncode != 0 and "transport 'ssh' not allowed" in ssh.stderr
