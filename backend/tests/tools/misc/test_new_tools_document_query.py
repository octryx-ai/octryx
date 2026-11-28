"""Document chunking and document knowledge queries over research bundles."""

from __future__ import annotations

import pytest

from tests.support.new_tools_support import _Ctx


def test_document_chunking_zero_limit_indexes_all_chunks():
    from app.services.document_ingestion.retrieval import _chunk_text

    text = "\n\n".join(f"Section {idx} " + ("content " * 120) for idx in range(8))

    bounded = _chunk_text(text, max_chunks=2)
    unbounded = _chunk_text(text, max_chunks=0)

    assert len(bounded) == 2
    assert len(unbounded) > len(bounded)
    assert unbounded[-1]["text"].endswith("content")


@pytest.mark.asyncio
async def test_query_document_knowledge_reads_research_bundle_without_project(tmp_path, db):
    from app.tools.documents import IngestDocumentSourceTool, QueryDocumentKnowledgeTool

    source = tmp_path / "shipping-summary.txt"
    source.write_text(
        "The routing server forwards shipping messages and the carrier confirms the parcel.\n",
        encoding="utf-8",
    )
    ctx = _Ctx(workspace_root=str(tmp_path), db=db, project_config={})

    ingest = await IngestDocumentSourceTool().execute(
        {
            "path": str(source),
            "topic": "Order shipping",
            "bundle_id": "shipping-protocol-no-project",
            "max_chunks": 4,
        },
        ctx,
    )

    query = await QueryDocumentKnowledgeTool().execute(
        {
            "query": "routing server carrier confirms parcel",
            "document_id": ingest["source"]["id"],
            "bundle_id": ingest["bundle_id"],
        },
        ctx,
    )

    assert query["retrieval_mode"] == "research_bundle"
    assert query["count"] >= 1
    assert "routing server" in query["matches"][0]["excerpt"].lower()
    assert query["matches"][0]["bundle_id"] == "shipping-protocol-no-project"


@pytest.mark.asyncio
async def test_query_document_knowledge_reads_normalized_html_bundle_without_project(tmp_path, db):
    from app.tools.documents import IngestDocumentSourceTool, QueryDocumentKnowledgeTool

    source = tmp_path / "ticketing.html"
    source.write_text(
        """
        <html>
          <body>
            <header>Site header</header>
            <h1>Ticket Enrichment</h1>
            <p>Enrichment attaches telemetry, job identifiers, and change context to tickets.</p>
            <p>This reduces operator back-and-forth during incident review.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    ctx = _Ctx(workspace_root=str(tmp_path), db=db, project_config={})

    ingest = await IngestDocumentSourceTool().execute(
        {
            "path": str(source),
            "topic": "Ticketing HTML",
            "bundle_id": "ticketing-html-query",
            "max_chunks": 4,
        },
        ctx,
    )

    query = await QueryDocumentKnowledgeTool().execute(
        {
            "query": "telemetry change context incident review",
            "document_id": ingest["source"]["id"],
            "bundle_id": ingest["bundle_id"],
        },
        ctx,
    )

    assert query["retrieval_mode"] == "research_bundle"
    assert query["count"] >= 1
    assert "telemetry" in query["matches"][0]["excerpt"].lower()
    assert "<html>" not in query["matches"][0]["excerpt"].lower()
