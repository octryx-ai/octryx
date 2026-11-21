"""The hands-on refusal names who holds the serve port (finding 30, top-10 #7)."""

from __future__ import annotations

import socket
import sys

from octryx_claude.hands_on_port import holder


def test_the_holder_of_a_listening_port_is_named():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        port = server.getsockname()[1]
        found = holder(f"http://127.0.0.1:{port}/")
        assert found.startswith(f"port {port} is used by ") and "(pid " in found
        assert "python" in found.lower() or sys.platform not in ("darwin", "linux")
    finally:
        server.close()


def test_a_free_port_has_no_holder():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    assert holder(f"http://127.0.0.1:{port}/") == ""
