from __future__ import annotations

from pathlib import Path
from typing import Any

from ..services.document_ingestion import ingest_document_source, query_document_knowledge
from .context import ToolContext


class IngestDocumentSourceTool:
    name = "ingest_document_source"
    description = (
        "Download or ingest a local document into the session workspace, parse it with liteparse/lit when needed, "
        "and write research bundle metadata (sources.json, citations.json)."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        workspace_root = Path(context.workspace_root or Path.cwd()).resolve()
        project_id = str(params.get("project_id") or context.project_config.get("project_id") or "").strip()
        return await ingest_document_source(
            db=context.db,
            workspace_root=workspace_root,
            project_id=project_id,
            path=str(params.get("path") or params.get("file_path") or "").strip(),
            url=str(params.get("url") or "").strip(),
            title_hint=str(params.get("title_hint") or params.get("source_title_hint") or "").strip(),
            topic=str(params.get("topic") or "").strip(),
            bundle_id=str(params.get("bundle_id") or "").strip(),
            citation_style=str(params.get("citation_style") or "ieee").strip().lower() or "ieee",
            max_pages=int(params.get("max_pages") or 200),
            max_chunks=int(params.get("max_chunks") or 80),
        )


class QueryDocumentKnowledgeTool:
    name = "query_document_knowledge"
    description = (
        "Search the session research bundles to answer questions about uploaded or ingested documents."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        project_id = str(params.get("project_id") or context.project_config.get("project_id") or "").strip()
        query = str(params.get("query") or "").strip()
        if not query:
            return {"error": "query is required"}
        return await query_document_knowledge(
            db=context.db,
            workspace_root=Path(context.workspace_root or Path.cwd()).resolve(),
            project_id=project_id,
            query=query,
            document_id=str(params.get("document_id") or params.get("source_id") or "").strip(),
            bundle_id=str(params.get("bundle_id") or "").strip(),
            limit=int(params.get("limit") or 8),
        )
