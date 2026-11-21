"""Seat calls share one pooled upstream client: before, each call built a new httpx client with its own
SSL context and connection, so every call paid a TLS handshake. A local HTTP/1.1 server counts the connections."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.model_gateway.inbound import seat_upstream


class _Counting(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive
    connections: set[tuple[str, int]] = set()

    def do_GET(self):  # noqa: N802 - http.server's naming
        _Counting.connections.add(self.client_address)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args):
        pass


@pytest.fixture
def upstream(monkeypatch):
    _Counting.connections = set()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Counting)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(seat_upstream, "seat_upstream_base_url", lambda *_a: f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(seat_upstream, "seat_transport", lambda: None)  # production: no mock transport
    yield
    server.shutdown()
    asyncio.run(seat_upstream.close_seat_clients())


def test_consecutive_seat_calls_reuse_one_connection(upstream):
    async def two_calls() -> None:
        for _ in range(2):
            client = seat_upstream.build_seat_client()
            assert (await client.get("/v1/ping")).status_code == 200
            await seat_upstream.release_seat_client(client)

    asyncio.run(two_calls())
    assert len(_Counting.connections) == 1, _Counting.connections


def test_a_shared_client_outlives_a_call_and_closes_at_shutdown(upstream):
    async def scenario() -> tuple[bool, bool, bool]:
        first = seat_upstream.build_seat_client()
        await seat_upstream.release_seat_client(first)
        second = seat_upstream.build_seat_client()
        open_after_release = not first.is_closed
        await seat_upstream.close_seat_clients()
        return first is second, open_after_release, first.is_closed

    same, open_after_release, closed_at_shutdown = asyncio.run(scenario())
    assert same and open_after_release and closed_at_shutdown


def test_another_event_loop_gets_its_own_client(upstream):
    async def one() -> object:
        return seat_upstream.build_seat_client()

    first, second = asyncio.run(one()), asyncio.run(one())
    assert first is not second
