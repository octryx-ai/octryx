"""Document source ingestion into research bundles: local text and HTML, remote HTML, title hints and the retired index."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import httpx
import pytest

from tests.egress_support import answer_public_web
from tests.new_tools_support import _Ctx

# ── document ingestion / research bundle ─────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_document_source_creates_research_bundle_for_local_text(tmp_path):
    from app.tools.documents import IngestDocumentSourceTool

    source = tmp_path / "source.txt"
    source.write_text("Enterprise LLM governance requires source controls and auditability.\n", encoding="utf-8")
    ctx = _Ctx(workspace_root=str(tmp_path))

    result = await IngestDocumentSourceTool().execute(
        {
            "path": str(source),
            "topic": "LLM Governance",
            "bundle_id": "llm-governance",
            "citation_style": "ieee",
        },
        ctx,
    )

    assert result["success"] is True
    assert result["bundle_id"] == "llm-governance"
    assert Path(result["sources_path"]).exists()
    assert Path(result["citations_path"]).exists()
    assert result["source"]["source_root_relative_path"].startswith("research/llm-governance/sources/")
    assert result["source"]["local_relative_path"].startswith("research/llm-governance/sources/")
    assert "/raw/" in result["source"]["local_relative_path"]
    assert "/parsed/" in result["source"]["parsed_relative_path"]
    assert "/evidence/" in result["source"]["evidence_record_relative_path"]
    assert result["source"]["evidence_manifest_relative_path"] == "research/llm-governance/evidence_manifest.json"
    assert result["source"]["content_id"].startswith("sha256:")
    assert result["source"]["origin"] == str(source)
    assert result["source"]["ingested_at"]
    evidence_record = json.loads(Path(result["evidence_record_path"]).read_text(encoding="utf-8"))
    assert evidence_record["origin_kind"] == "file"
    assert evidence_record["raw_relative_path"] == result["source"]["local_relative_path"]
    assert evidence_record["content_sha256"] == result["source"]["content_sha256"]
    evidence_manifest = json.loads(Path(result["evidence_manifest_path"]).read_text(encoding="utf-8"))
    assert evidence_manifest[0]["source_id"] == result["source"]["id"]
    citations = json.loads(Path(result["citations_path"]).read_text(encoding="utf-8"))
    assert citations[0]["citation_style"] == "ieee"
    assert citations[0]["content_id"] == result["source"]["content_id"]
    assert "Enterprise LLM governance" in result["content_preview"]


@pytest.mark.asyncio
async def test_ingest_document_source_normalizes_local_html_to_markdown(tmp_path):
    from app.tools.documents import IngestDocumentSourceTool

    source = tmp_path / "source.html"
    source.write_text(
        """
        <html>
          <body>
            <nav>Navigation</nav>
            <h1>Corporate Ticketing Overview</h1>
            <p>Enterprise teams need structured ticket identifiers.</p>
            <ul><li>Auditability</li><li>Traceability</li></ul>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    ctx = _Ctx(workspace_root=str(tmp_path))

    result = await IngestDocumentSourceTool().execute(
        {
            "path": str(source),
            "topic": "Ticketing HTML",
            "bundle_id": "ticketing-html",
            "citation_style": "ieee",
        },
        ctx,
    )

    parsed_path = Path(result["source"]["parsed_path"])
    parsed_text = parsed_path.read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["source"]["parser"] == "html_markdown"
    assert "# Corporate Ticketing Overview" in parsed_text
    assert "Enterprise teams need structured ticket identifiers." in parsed_text
    assert "- Auditability" in parsed_text
    assert "<html>" not in parsed_text
    assert "<nav>" not in parsed_text
    assert "Navigation" not in parsed_text
    assert "# Corporate Ticketing Overview" in result["content_preview"]


@pytest.mark.asyncio
async def test_ingest_document_source_parses_remote_html_with_non_html_suffix(tmp_path, monkeypatch):
    from app.services.document_ingestion import ingest_document_source

    async def _resolve_hostname_ips(hostname: str, port: int | None):
        assert hostname == "developer.example.com"
        return {ipaddress.ip_address("93.184.216.34")}

    def _handler(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=(
                b"<html><head><title>Service Desk Developer Portal</title></head><body><p>01/06/2026</p>"
                b"<p>REST API reference and webhook guidance.</p></body></html>"
            ),
            request=request,
        )

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve_hostname_ips)
    answer_public_web(monkeypatch, lambda request: _handler(str(request.url)))

    result = await ingest_document_source(
        db=None,
        workspace_root=tmp_path,
        url="https://developer.example.com/dev.do",
        topic="Ticketing API Integration",
        bundle_id="remote-html-do",
    )

    parsed_path = Path(result["source"]["parsed_path"])
    parsed_text = parsed_path.read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["source"]["file_name"] == "dev.do"
    assert result["source"]["media_type"].startswith("text/html")
    assert result["source"]["parser"] == "html_markdown"
    assert result["source"]["parse_success"] is True
    assert result["source"]["title"] == "Service Desk Developer Portal"
    assert result["source"]["local_relative_path"].startswith("research/remote-html-do/sources/")
    assert "/raw/" in result["source"]["local_relative_path"]
    evidence_record = json.loads(Path(result["evidence_record_path"]).read_text(encoding="utf-8"))
    assert evidence_record["origin_kind"] == "url"
    assert evidence_record["requested_url"] == "https://developer.example.com/dev.do"
    assert evidence_record["final_url"] == "https://developer.example.com/dev.do"
    assert evidence_record["status_code"] == 200
    assert evidence_record["response_headers"]["content-type"].startswith("text/html")
    assert evidence_record["raw_relative_path"] == result["source"]["local_relative_path"]
    assert "REST API reference and webhook guidance." in parsed_text


@pytest.mark.asyncio
async def test_ingest_document_source_prefers_title_hint_over_weak_parsed_title(tmp_path):
    from app.tools.documents import IngestDocumentSourceTool

    source = tmp_path / "source.html"
    source.write_text(
        """
        <html>
          <body>
            <h1>01/06/2026</h1>
            <p>Enterprise ticketing API integration guidance for webhook, REST, and rollout planning.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    ctx = _Ctx(workspace_root=str(tmp_path))

    result = await IngestDocumentSourceTool().execute(
        {
            "path": str(source),
            "topic": "Ticketing API Integration",
            "bundle_id": "ticketing-api-title-hint",
            "citation_style": "ieee",
            "title_hint": "Ticketing API Integration Guide",
        },
        ctx,
    )

    assert result["success"] is True
    assert result["source"]["title"] == "Ticketing API Integration Guide"
    sources = json.loads(Path(result["sources_path"]).read_text(encoding="utf-8"))
    assert sources[0]["title"] == "Ticketing API Integration Guide"


@pytest.mark.asyncio
async def test_ingest_document_source_prefers_title_hint_over_generic_markdown_link_title(tmp_path):
    from app.tools.documents import IngestDocumentSourceTool

    source = tmp_path / "jira-api.md"
    source.write_text(
        "[Developer](https://developer.atlassian.com/) Documentation\n\n"
        "Jira REST API reference material for issues, rate limits, and webhooks.\n",
        encoding="utf-8",
    )
    ctx = _Ctx(workspace_root=str(tmp_path))

    result = await IngestDocumentSourceTool().execute(
        {
            "path": str(source),
            "topic": "Ticketing API Integration",
            "bundle_id": "ticketing-api-title-hint",
            "citation_style": "ieee",
            "title_hint": "Jira Issues API reference",
        },
        ctx,
    )

    assert result["success"] is True
    assert result["source"]["title"] == "Jira Issues API reference"
    evidence_record = json.loads(Path(result["evidence_record_path"]).read_text(encoding="utf-8"))
    assert evidence_record["title"] == "Jira Issues API reference"
