"""Contract: the research-package fetch resolves once and connects to what it checked."""

from __future__ import annotations

import ipaddress
import socket

import httpcore
import pytest

from app.config import Settings
from app.services.knowledge.sources.web_fetch import FetchRefusedError, fetch_public_document

GLOBAL = "93.184.215.14"
REBOUND = "10.0.0.5"
DOCUMENTATION = "203.0.113.10"
_RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 5\r\n\r\nhello"


class _Stream(httpcore.AsyncNetworkStream):
    def __init__(self, record: dict) -> None:
        self._record = record
        self._response = _RESPONSE

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        chunk, self._response = self._response[:max_bytes], self._response[max_bytes:]
        return chunk

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self._record["server_hostname"] = server_hostname
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
def dns(monkeypatch):
    answers: dict[str, list[str]] = {}
    lookups: list[str] = []

    async def _resolve(hostname: str, port: int | None):
        lookups.append(hostname)
        queue = answers.get(hostname) or []
        if not queue:
            return set()
        return {ipaddress.ip_address(queue.pop(0) if len(queue) > 1 else queue[0])}

    def _no_second_lookup(*args, **kwargs):
        raise AssertionError("the connection must not resolve the hostname again")

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr(socket, "getaddrinfo", _no_second_lookup)
    monkeypatch.setattr("app.config.get_settings", lambda: Settings.model_construct(web_fetch_proxy_url=""))
    return answers, lookups


@pytest.mark.asyncio
async def test_a_rebind_after_the_check_is_never_connected(dns):
    answers, lookups = dns
    answers["docs.example.test"] = [GLOBAL, REBOUND]
    backend = _RecordingBackend()

    document = await fetch_public_document("https://docs.example.test/guide.md", network_backend=backend)
    assert (document.media_type, document.data) == ("text/markdown", b"hello")
    assert backend.connects == [(GLOBAL, 443)]
    assert lookups == ["docs.example.test"]
    assert backend.record["server_hostname"] == "docs.example.test"

    with pytest.raises(FetchRefusedError) as refused:
        await fetch_public_document("https://docs.example.test/guide.md", network_backend=backend)
    assert refused.value.reason == "not_public_address"
    assert backend.connects == [(GLOBAL, 443)]


@pytest.mark.asyncio
async def test_the_stricter_address_rule_holds_on_the_pinned_path(dns):
    answers, _lookups = dns
    answers["doc-range.example.test"] = [DOCUMENTATION]
    backend = _RecordingBackend()

    with pytest.raises(FetchRefusedError) as refused:
        await fetch_public_document("https://doc-range.example.test/a.md", network_backend=backend)
    assert refused.value.reason == "not_public_address"
    with pytest.raises(FetchRefusedError) as unresolvable:
        await fetch_public_document("https://nowhere.example.test/a.md", network_backend=backend)
    assert unresolvable.value.reason == "unresolvable"
    assert backend.connects == []
