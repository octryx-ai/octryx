"""Contract: the uncredentialed web fetch is pinned and never uses an implicit proxy.

- a DNS answer that changes after the check (rebinding) is never connected: the fetch connects to
  the checked address, resolved once, and the next fetch after the rebind is refused before any
  connect;
- environment proxies are ignored: with ``HTTP(S)_PROXY``/``ALL_PROXY`` set, the fetch connects
  directly;
- a proxy is used only when ``OCTRYX_WEB_FETCH_PROXY_URL`` names one; the target is still
  checked first, and an unusable setting refuses every fetch instead of connecting directly.
"""

from __future__ import annotations

import ipaddress
import socket

import httpcore
import pytest

from app.config import Settings
from app.services.outbound_egress import EgressRefusedError
from app.services.outbound_egress.public_web import REASON_PROXY_INVALID, public_web_client

CHECKED = "203.0.113.10"
REBOUND = "10.0.0.5"
PROXY = "http://proxy.corp.example:3128"


class _Stream(httpcore.AsyncNetworkStream):
    def __init__(self, record: dict) -> None:
        self._record = record
        self._response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        chunk, self._response = self._response[:max_bytes], self._response[max_bytes:]
        return chunk

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._record["sent"] = self._record.get("sent", b"") + buffer

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
def rebinding_dns(monkeypatch):
    answers: list[str] = []

    async def _resolve(hostname: str, port: int | None):
        answers.append(hostname)
        return {ipaddress.ip_address(CHECKED if len(answers) == 1 else REBOUND)}

    def _no_second_lookup(*args, **kwargs):
        raise AssertionError("the connection must not resolve the hostname again")

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr(socket, "getaddrinfo", _no_second_lookup)
    return answers


def _proxy_setting(monkeypatch, value: str) -> None:
    monkeypatch.setattr("app.config.get_settings", lambda: Settings.model_construct(web_fetch_proxy_url=value))


@pytest.mark.asyncio
async def test_a_rebind_after_the_check_is_never_connected(rebinding_dns):
    backend = _RecordingBackend()
    async with public_web_client(timeout=5, network_backend=backend) as client:
        response = await client.get("https://docs.example.test/guide")
    assert response.status_code == 200 and response.text == "ok"
    assert backend.connects == [(CHECKED, 443)]
    assert rebinding_dns == ["docs.example.test"]  # resolved exactly once
    assert backend.record["server_hostname"] == "docs.example.test"

    # The name now answers a private address: refused before anything is connected or sent.
    async with public_web_client(timeout=5, network_backend=backend) as client:
        with pytest.raises(EgressRefusedError) as refused:
            await client.get("https://docs.example.test/guide")
    assert refused.value.reason == "private_address_not_allowlisted"
    assert backend.connects == [(CHECKED, 443)]


@pytest.mark.asyncio
async def test_environment_proxies_are_never_used(rebinding_dns, monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, PROXY)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    _proxy_setting(monkeypatch, "")
    backend = _RecordingBackend()
    async with public_web_client(timeout=5, network_backend=backend) as client:
        assert (await client.get("https://docs.example.test/guide")).status_code == 200
    assert backend.connects == [(CHECKED, 443)]  # directly to the checked address, not the proxy


@pytest.mark.asyncio
async def test_a_named_proxy_is_used_only_when_configured_and_the_target_is_still_checked(monkeypatch):
    async def _public(hostname: str, port: int | None):
        return {ipaddress.ip_address(CHECKED)}

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _public)
    _proxy_setting(monkeypatch, PROXY)
    backend = _RecordingBackend()
    async with public_web_client(timeout=5, network_backend=backend) as client:
        assert (await client.get("http://docs.example.test/guide")).status_code == 200
        with pytest.raises(EgressRefusedError) as refused:
            await client.get("http://127.0.0.1:2480/")
    assert refused.value.reason == "blocked_address"
    assert backend.connects == [("proxy.corp.example", 3128)]
    assert backend.record["sent"].startswith(b"GET http://docs.example.test/guide HTTP/1.1")


@pytest.mark.parametrize("value", ["socks5://proxy.corp.example:1080", "proxy.corp.example:3128", "http://p/x?y=1"])
@pytest.mark.asyncio
async def test_an_unusable_proxy_setting_refuses_every_fetch(monkeypatch, value):
    _proxy_setting(monkeypatch, value)
    with pytest.raises(EgressRefusedError) as refused:
        public_web_client(timeout=5, network_backend=_RecordingBackend())
    assert refused.value.reason == REASON_PROXY_INVALID
    assert value not in str(refused.value)

    from app.tools.runtime_impl._runtime_bash_web import WebFetchTool

    result = await WebFetchTool().execute({"url": "https://docs.example.test/guide"}, None)
    assert result["error"] == f"Fetch failed: egress_refused: {REASON_PROXY_INVALID}"
