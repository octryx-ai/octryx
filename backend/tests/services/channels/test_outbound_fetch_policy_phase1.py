from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services.document_ingestion import ingest_document_source
from tests.egress_support import answer_public_web


@dataclass
class _Ctx:
    workspace_root: str | None = None
    session_id: str | None = None
    db: Any = None
    project_config: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    project_ids: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    system_context: str | None = None
    parent_session_id: str | None = None
    sub_agent_depth: int = 0
    agent_definition: Any = None


def _unexpected(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected outbound request: {request.url}")


async def _example_dns(hostname: str, port: int | None):
    assert hostname == "example.com"
    return {ipaddress.ip_address("93.184.216.34")}


@pytest.mark.asyncio
async def test_web_fetch_blocks_localhost_target(monkeypatch):
    from app.tools.runtime_impl._runtime_bash_web import WebFetchTool

    answer_public_web(monkeypatch, _unexpected)

    result = await WebFetchTool().execute({"url": "http://127.0.0.1:8000/admin"}, _Ctx())

    assert result["error"] == "Fetch failed: egress_refused: blocked_address"


@pytest.mark.asyncio
async def test_web_fetch_allows_external_https(monkeypatch):
    from app.tools.runtime_impl._runtime_bash_web import WebFetchTool

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _example_dns)
    answer_public_web(
        monkeypatch,
        lambda request: httpx.Response(200, headers={"content-type": "text/plain; charset=utf-8"}, text="public content"),
    )

    result = await WebFetchTool().execute({"url": "https://example.com/report.txt"}, _Ctx())

    assert result["format"] == "text"
    assert result["content"] == "public content"


@pytest.mark.asyncio
async def test_fetch_and_save_knowledge_blocks_metadata_hostname(monkeypatch):
    from app.tools.knowledge_impl._knowledge_fetch import FetchAndSaveKnowledgeTool

    answer_public_web(monkeypatch, _unexpected)

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "url", "query": "https://metadata.google.internal/computeMetadata/v1"},
        _Ctx(db=object()),
    )

    assert result["error"] == "HTTP fetch failed: egress_refused: blocked_host"


@pytest.mark.asyncio
async def test_fetch_and_save_knowledge_allows_external_url(monkeypatch):
    from app.tools.knowledge_impl._knowledge_fetch import FetchAndSaveKnowledgeTool

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _example_dns)
    answer_public_web(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Example</title></head><body><h1>Allowed</h1></body></html>",
        ),
    )

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "url", "query": "https://example.com/docs"},
        _Ctx(db=object()),
    )

    assert result["status"] == "fetched"
    assert result["saved"] is False
    assert result["source"] == "url"
    assert result["source_uri"] == "https://example.com/docs"
    assert result["title"] == "Example"


@pytest.mark.asyncio
async def test_ingest_document_source_blocks_redirect_to_private_target(tmp_path, monkeypatch):
    requested: list[str] = []

    def _redirect(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/internal.pdf"})

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _example_dns)
    answer_public_web(monkeypatch, _redirect)

    result = await ingest_document_source(
        db=None,
        workspace_root=tmp_path,
        url="https://example.com/research.pdf",
        bundle_id="redirect-block",
    )

    assert result["error"] == "Download failed: source_download_blocked error_type=EgressRefusedError"
    assert result["policy_reason"] == "blocked_address"
    assert "127.0.0.1" not in str(result)
    assert requested == ["https://example.com/research.pdf"]  # the redirect hop was never sent


@pytest.mark.asyncio
async def test_ingest_document_source_allows_external_download(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _example_dns)
    answer_public_web(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=utf-8"},
            content=b"Enterprise controls require traceable approvals.\n",
        ),
    )

    result = await ingest_document_source(
        db=None,
        workspace_root=tmp_path,
        url="https://example.com/research.txt",
        bundle_id="public-download",
    )

    assert result["success"] is True
    assert result["source"]["url"] == "https://example.com/research.txt"
    assert Path(result["source"]["local_file_path"]).exists()
