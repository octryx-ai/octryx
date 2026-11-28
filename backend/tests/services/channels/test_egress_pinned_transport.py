"""Contract: a credentialed request connects only to the address the egress check resolved."""

from __future__ import annotations

import asyncio
import ipaddress
import pathlib
import socket

import httpcore
import httpx
import pytest

from app.services.knowledge.sources.sync.connections import SourceConnection
from app.services.knowledge.sources.sync.http import SourceReader
from app.services.outbound_egress import CONNECTION_JIRA, EgressRefusedError, PinnedEgressTransport
from app.services.outbound_egress.pinned_transport import REASON_UNPINNED_TARGET, _PinnedNetworkBackend
from tests.egress_support import stub_settings, use_stub_settings

APP = pathlib.Path(__file__).resolve().parents[3] / "app"
CHECKED = "203.0.113.10"
REBOUND = "10.0.0.5"


class _Stream(httpcore.AsyncNetworkStream):
    def __init__(self, record: dict) -> None:
        self._record = record
        self._response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        chunk, self._response = self._response[:max_bytes], self._response[max_bytes:]
        return chunk

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._record.setdefault("sent", b"")
        self._record["sent"] += buffer

    async def aclose(self) -> None:
        return None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self._record["server_hostname"] = server_hostname
        self._record["check_hostname"] = ssl_context.check_hostname
        return self

    def get_extra_info(self, info: str):
        return None


class _RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.connects: list[tuple[str, int]] = []
        self.record: dict = {}

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connects.append((host, port))
        return _Stream(self.record)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise AssertionError("no unix socket")

    async def sleep(self, seconds: float) -> None:
        return None


@pytest.fixture
def rebinding_dns(monkeypatch):
    answers: list[str] = []

    async def _resolve(hostname: str, port: int | None):
        answers.append(hostname)
        return {ipaddress.ip_address(CHECKED if len(answers) == 1 else REBOUND)}

    def _no_second_lookup(*args, **kwargs):
        raise AssertionError("the connection must not resolve the hostname again")

    async def _no_allowlist(connection: str) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr(socket, "getaddrinfo", _no_second_lookup)
    monkeypatch.setattr("app.services.outbound_egress.target_check._private_host_keys", _no_allowlist)
    return answers


@pytest.mark.asyncio
async def test_the_request_connects_to_the_checked_address_with_the_original_host_and_sni(rebinding_dns):
    backend = _RecordingBackend()
    transport = PinnedEgressTransport(CONNECTION_JIRA, network_backend=backend)
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://jira.example.test/rest/api/2/myself", auth=("bot", "token"))

    assert response.status_code == 200 and response.text == "ok"
    assert backend.connects == [(CHECKED, 443)]  # the checked IP, never the rebound one
    assert rebinding_dns == ["jira.example.test"]
    assert backend.record["server_hostname"] == "jira.example.test"  # SNI and certificate name
    assert backend.record["check_hostname"] is True
    assert b"Host: jira.example.test\r\n" in backend.record["sent"]

    # The name now rebinds to a private address: the next request is refused before any connect.
    async with httpx.AsyncClient(transport=PinnedEgressTransport(CONNECTION_JIRA, network_backend=backend)) as client:
        with pytest.raises(EgressRefusedError) as refused:
            await client.get("https://jira.example.test/rest/api/2/myself", auth=("bot", "token"))
    assert refused.value.reason == "private_address_not_allowlisted"
    assert REBOUND not in str(refused.value) and "jira.example.test" not in str(refused.value)
    assert backend.connects == [(CHECKED, 443)]


@pytest.mark.asyncio
async def test_a_target_the_transport_did_not_check_is_never_connected():
    backend = _RecordingBackend()
    pinned = _PinnedNetworkBackend({("jira.example.test", 443): (CHECKED,)}, backend)

    with pytest.raises(httpcore.ConnectError) as refused:
        await pinned.connect_tcp("other.example.test", 443)
    assert REASON_UNPINNED_TARGET in str(refused.value)
    await pinned.connect_tcp("jira.example.test", 443)
    assert backend.connects == [(CHECKED, 443)]


@pytest.mark.asyncio
async def test_a_listed_local_stub_is_reached_over_a_real_pinned_socket(monkeypatch):
    seen: list[bytes] = []

    async def _stub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        body = b'{"ok": true}'
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(_stub, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    use_stub_settings(monkeypatch, stub_settings(hosts=f"127.0.0.1:{port}"))
    connection = SourceConnection(kind="jira", base_url=f"http://127.0.0.1:{port}", principal="bot", secret="pw")
    try:
        assert await SourceReader(connection).get_json("/rest/api/2/serverInfo") == {"ok": True}
    finally:
        server.close()
        await server.wait_closed()
    assert f"Host: 127.0.0.1:{port}\r\n".encode() in seen[0]


def test_every_credentialed_client_uses_the_pinned_transport():
    sources = {path: path.read_text() for path in APP.rglob("*.py")}
    assert not [p for p, text in sources.items() if "egress_hooks" in text]
    assert not (APP / "services" / "outbound_egress_hooks.py").exists()
    # The uncredentialed web fetches are pinned too: no unpinned redirect helper remains.
    unpinned = sorted(
        str(p.relative_to(APP))
        for p, text in sources.items()
        if "request_with_url_policy" in text or "get_url_with_policy" in text
    )
    assert unpinned == []
    pinned_modules = [p for p, text in sources.items() if "egress_transport(" in text]
    assert len(pinned_modules) >= 30
