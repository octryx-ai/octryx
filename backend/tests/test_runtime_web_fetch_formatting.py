from __future__ import annotations

import ipaddress
from types import SimpleNamespace

import httpx
import pytest

from app.tools.runtime_impl._runtime_web_fetch_formatting import format_web_fetch_content
from tests.egress_support import answer_public_web


def test_format_web_fetch_content_returns_truncated_html_preview() -> None:
    result = format_web_fetch_content("x" * 8100, content_type="text/html; charset=utf-8", requested_format="html")

    assert result["format"] == "html"
    assert result["content"].endswith("\n...[truncated]")
    assert len(result["content"]) == 8015


def test_format_web_fetch_content_converts_html_to_text_links(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.tools.runtime_impl._runtime_web_fetch_formatting.html_to_markdown",
        lambda _text: "See [Example](https://example.com/docs)",
    )

    result = format_web_fetch_content(
        "<html><body>ignored</body></html>",
        content_type="text/html",
        requested_format="text",
    )

    assert result == {"content": "See https://example.com/docs", "format": "text"}


def test_format_web_fetch_content_keeps_plain_text_as_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.tools.runtime_impl._runtime_web_fetch_formatting.html_to_markdown",
        lambda _text: (_ for _ in ()).throw(AssertionError("html_to_markdown should not be called")),
    )

    result = format_web_fetch_content("plain text", content_type="text/plain", requested_format="markdown")

    assert result == {"content": "plain text", "format": "text"}


@pytest.mark.asyncio
async def test_web_fetch_tool_uses_shared_formatting_helper(monkeypatch) -> None:
    from app.tools.runtime_impl._runtime_bash_web import WebFetchTool

    captured: dict[str, object] = {}

    async def _resolve_hostname_ips(hostname: str, port: int | None):
        assert hostname == "example.com"
        return {ipaddress.ip_address("93.184.216.34")}

    def _handler(method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><body>ignored</body></html>",
            request=request,
        )

    def _format_web_fetch_content(text: str, *, content_type: str, requested_format: str):
        captured["text"] = text
        captured["content_type"] = content_type
        captured["requested_format"] = requested_format
        return {"content": "formatted body", "format": "markdown"}

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve_hostname_ips)
    answer_public_web(monkeypatch, lambda request: _handler(request.method, str(request.url)))
    monkeypatch.setattr("app.tools.runtime_impl._runtime_bash_web.format_web_fetch_content", _format_web_fetch_content)

    result = await WebFetchTool().execute(
        {"url": "https://example.com/report", "format": "markdown"},
        SimpleNamespace(),
    )

    assert captured == {
        "text": "<html><body>ignored</body></html>",
        "content_type": "text/html; charset=utf-8",
        "requested_format": "markdown",
    }
    assert result == {
        "url": "https://example.com/report",
        # The page is the source (E1): no <title>, so its URL names it.
        "source_title": "https://example.com/report",
        "source_url": "https://example.com/report",
        "cite_as": "[https://example.com/report](https://example.com/report)",
        "content": "formatted body",
        "format": "markdown",
    }
