from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.document_ingestion.common import MAX_PREVIEW_CHARS, _ensure_bundle_root
from app.services.document_ingestion.ingest_records import BundleRecords, build_source, write_bundle_records
from app.services.document_ingestion.parse import ParsedDocument, parse_document_file
from app.services.document_ingestion.retrieval import _query_research_bundle
from app.services.document_ingestion.source_fetch import download_source, source_title, store_local_source

__all__ = [
    "ingest_document_source",
    "query_document_knowledge",
]

async def ingest_document_source(
    *,
    db: AsyncSession | None,
    workspace_root: Path,
    project_id: str = "",
    path: str = "",
    url: str = "",
    title_hint: str = "",
    topic: str = "",
    bundle_id: str = "",
    citation_style: str = "ieee",
    max_pages: int = 200,
    max_chunks: int = 80,
) -> dict[str, Any]:
    if not path and not url:
        return {"error": "path or url is required"}
    bundle_root = _ensure_bundle_root(workspace_root, topic=topic or "research", bundle_id=bundle_id)
    origin = url or path
    source_url = str(url or "").strip()
    if source_url:
        stored = await download_source(source_url, origin=origin, bundle_root=bundle_root)
        if isinstance(stored, dict):
            return stored
    else:
        stored = store_local_source(path, origin=origin, workspace_root=workspace_root, bundle_root=bundle_root)

    parsed = await asyncio.to_thread(
        parse_document_file,
        stored.local_path,
        parsed_dir=stored.archive_dirs["parsed_dir"],
        media_type=stored.content_type,
        max_pages=max_pages,
    )
    preview_text = parsed.text[:MAX_PREVIEW_CHARS] if parsed.text else ""
    title = source_title(parsed, stored.local_path, stored.content_type, title_hint)
    source = build_source(
        stored, parsed, title=title, origin=origin, bundle_root=bundle_root, workspace_root=workspace_root,
        citation_style=citation_style,
    )
    records = write_bundle_records(
        source, stored, parsed, source_url=source_url, bundle_root=bundle_root, workspace_root=workspace_root
    )
    return _ingest_answer(parsed, source, records, bundle_root=bundle_root, preview_text=preview_text)


def _ingest_answer(
    parsed: ParsedDocument, source: dict[str, Any], records: BundleRecords, *, bundle_root: Path, preview_text: str,
) -> dict[str, Any]:
    return {
        "success": parsed.success,
        "bundle_id": bundle_root.name,
        "bundle_path": str(bundle_root),
        "sources_path": str(bundle_root / "sources.json"),
        "citations_path": str(bundle_root / "citations.json"),
        "source": source,
        "sources_count": len(records.sources),
        "citations_count": len(records.citations),
        "evidence_count": len(records.evidence_records),
        "evidence_manifest_path": str(records.evidence_manifest_path),
        "evidence_record_path": str(records.evidence_record_path),
        "content_preview": preview_text,
        "artifacts": records.artifacts,
        "archive_artifacts": records.archive_artifacts,
        **({"warning": parsed.error} if parsed.error else {}),
    }


async def query_document_knowledge(
    *,
    db: AsyncSession,
    workspace_root: Path | None = None,
    project_id: str,
    query: str,
    document_id: str = "",
    bundle_id: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    """Search the session's research bundles."""
    if workspace_root is not None:
        return _query_research_bundle(
            workspace_root=workspace_root,
            bundle_id=bundle_id,
            query=query,
            document_id=document_id,
            limit=limit,
        )
    return {"error": "workspace_root is required: documents are searched in the session research bundles"}
