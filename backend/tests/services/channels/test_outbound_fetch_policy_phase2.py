from __future__ import annotations

import ipaddress
from types import SimpleNamespace

import httpx
import pytest

from app.services.outbound_url_policy import OutboundURLPolicyError
from tests.egress_support import answer_public_web


async def _example_dns(hostname: str, port: int | None):
    assert hostname == "example.com"
    return {ipaddress.ip_address("93.184.216.34")}


def _sent(request: httpx.Request) -> dict[str, object]:
    return {
        "method": request.method,
        "url": str(request.url),
        "x_test": request.headers.get("x-test"),
        "content": request.content.decode(),
    }


@pytest.mark.asyncio
async def test_http_request_tool_allows_public_post_request(monkeypatch):
    from app.tools.runtime_impl._runtime_workspace_http import HttpRequestTool

    calls: list[dict[str, object]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(_sent(request))
        return httpx.Response(200, headers={"content-type": "application/json"}, text='{"ok": true}')

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _example_dns)
    answer_public_web(monkeypatch, _handler)

    result = await HttpRequestTool().execute(
        {
            "method": "POST",
            "url": "https://example.com/api",
            "headers": {"X-Test": "1"},
            "query": {"page": "1"},
            "body": {"payload": True},
        },
        SimpleNamespace(),
    )

    assert result["status_code"] == 200
    assert result["body"] == '{"ok": true}'
    assert calls == [
        {"method": "POST", "url": "https://example.com/api?page=1", "x_test": "1", "content": '{"payload": true}'}
    ]


@pytest.mark.asyncio
async def test_http_request_tool_blocks_redirect_to_private_target(monkeypatch):
    from app.tools.runtime_impl._runtime_workspace_http import HttpRequestTool

    calls: list[dict[str, object]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(_sent(request))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/internal"})

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _example_dns)
    answer_public_web(monkeypatch, _handler)

    result = await HttpRequestTool().execute(
        {"method": "POST", "url": "https://example.com/api", "body": "payload"},
        SimpleNamespace(),
    )

    assert result["error"] == "Request failed: egress_refused: blocked_address"
    assert calls == [{"method": "POST", "url": "https://example.com/api", "x_test": None, "content": "payload"}]


@pytest.mark.asyncio
async def test_fetch_github_releases_blocks_redirect_to_private_target(monkeypatch):
    from app.services.design_delivery_sync.github_fetch import fetch_github_releases

    async def _resolved_github_config(_db):
        return {
            "github_url": "https://api.github.example.com",
            "github_token": "token",
        }

    async def _resolve_hostname_ips(hostname: str, port: int | None):
        assert hostname == "api.github.example.com"
        return {ipaddress.ip_address("140.82.113.5")}

    sent: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    from app.services.outbound_egress import egress_transport

    monkeypatch.setattr(
        "app.services.design_delivery_sync.github_fetch._resolved_github_config",
        _resolved_github_config,
    )
    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve_hostname_ips)
    monkeypatch.setattr(
        "app.services.design_delivery_sync.github_fetch.egress_transport",
        lambda connection: egress_transport(connection, inner=httpx.MockTransport(_handler)),
    )

    # The pinned GitHub transport checks the redirect hop and refuses it before it is sent.
    with pytest.raises(OutboundURLPolicyError) as refused:
        await fetch_github_releases(SimpleNamespace(), owner="acme", repo="platform", limit=10)
    assert refused.value.reason == "blocked_address"
    assert sent == ["https://api.github.example.com/repos/acme/platform/releases?per_page=10"]
