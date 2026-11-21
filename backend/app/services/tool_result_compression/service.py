from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ToolResultCompressionLog, ToolResultCompressor
from .budget import (
    DEFAULT_COMPACT_RESULT_TOKEN_BUDGET,
    compact_result_token_budget,
    enforce_compact_result_budget,
)
from .evidence_contracts import attach_evidence_contract
from .governance import (
    get_effective_default_compressor_catalog,
    get_effective_default_compressor_definition,
)
from .registry import get_strategy_handler, is_supported_strategy
from .support import _estimate_tokens, _serialize_compression_log, _serialize_compressor

MAX_COMPACT_RESULT_TOKENS = DEFAULT_COMPACT_RESULT_TOKEN_BUDGET
DEFAULT_COMPRESSORS: dict[str, dict[str, Any]] = {
    "run_kubectl": {"strategy": "k8s_pod_failures", "config": {"max_items": 50}},
    "kubernetes_topology_snapshot": {
        "strategy": "kubernetes_topology_snapshot_summary",
        "config": {"max_warnings": 20, "max_diagram_nodes": 1000, "max_diagram_edges": 2000},
    },
    "list_grafana_alerts": {"strategy": "grafana_firing_only", "config": {"max_items": 50}},
    "search_jira_tickets": {
        "strategy": "jira_extract_fields",
        "config": {"max_items": 20, "max_summary_chars": 140, "compact_token_budget": 4500},
    },
    "list_recent_bitbucket_commits": {
        "strategy": "bitbucket_recent_commit_summary",
        "config": {
            "max_repositories": 10,
            "max_commits_per_repo": 3,
            "max_global_commits": 12,
            "max_message_chars": 140,
            "compact_token_budget": 4500,
        },
    },
    "list_bitbucket_pull_requests": {
        "strategy": "bitbucket_pull_request_summary",
        "config": {"max_pull_requests": 100},
    },
    "search_confluence": {
        "strategy": "confluence_search_summary",
        "config": {"max_results": 8},
    },
    "get_confluence_page": {
        "strategy": "confluence_page_summary",
        "config": {"max_headings": 10, "max_excerpt_chars": 1200},
    },
    "list_workspace_git_commits": {
        "strategy": "workspace_git_commit_summary",
        "config": {"max_commits": 150},
    },
    "read_office_document": {
        "strategy": "office_document_view_summary",
        "config": {"max_excerpt_chars": 1800, "max_issues": 40},
    },
    "get_office_element": {
        "strategy": "office_element_summary",
        "config": {"max_children": 40, "max_excerpt_chars": 1200},
    },
    "query_office_elements": {
        "strategy": "office_query_summary",
        "config": {"max_matches": 80},
    },
    "get_presentation_html": {
        "strategy": "office_html_summary",
        "config": {"max_headings": 12, "max_excerpt_chars": 1400},
    },
    "ingest_document_source": {
        "strategy": "document_ingest_summary",
        "config": {"max_artifacts": 12, "max_preview_chars": 1200},
    },
    "get_context_from_subthreads": {
        "strategy": "subthread_context_summary",
        "config": {
            "max_accepted_subthreads": 8,
            "max_rejected_subthreads": 8,
            "max_sources_per_thread": 8,
            "max_response_chars": 480,
            "max_task_chars": 220,
        },
    },
    "query_loki": {"strategy": "loki_tail_errors", "config": {"tail_lines": 50, "error_lines": 50}},
    "code_structure_snapshot": {
        "strategy": "code_structure_snapshot_summary",
        "config": {
            "max_diagram_nodes": 240,
            "max_diagram_edges": 400,
            "max_warnings": 20,
            # A full-repository terraform brief under the module quota
            # (~211 nodes on the reference infrastructure repo) compacts to
            # ~35k tokens even after the prefix strip; the previous 24k
            # budget pushed it into the diagram shrink ladder, which cut the
            # history brief to 40 nodes and silently collapsed the
            # module-detail diagram set to one module.
            "compact_token_budget": 48000,
        },
    },
    "aws_topology_snapshot": {
        "strategy": "aws_topology_snapshot_summary",
        "config": {"max_nodes_per_service": 0, "max_warnings": 20},
    },
}


async def ensure_default_tool_result_compressors(db: AsyncSession) -> None:
    rows = (await db.execute(select(ToolResultCompressor))).scalars().all()
    existing_by_tool_name = {row.tool_name: row for row in rows}
    effective_defaults = await get_effective_default_compressor_catalog(db, defaults=DEFAULT_COMPRESSORS)
    for tool_name, payload in effective_defaults.items():
        if tool_name in existing_by_tool_name:
            continue
        db.add(
            ToolResultCompressor(
                id=str(uuid.uuid4()),
                tool_name=tool_name,
                strategy=str(payload["strategy"]),
                config=dict(payload.get("config") or {}),
                is_active=bool(payload.get("is_active", True)),
            )
        )
    await db.flush()


async def list_tool_result_compressors(db: AsyncSession) -> list[dict[str, Any]]:
    await ensure_default_tool_result_compressors(db)
    rows = (await db.execute(select(ToolResultCompressor).order_by(ToolResultCompressor.tool_name))).scalars().all()
    return [_serialize_compressor(row) for row in rows]


async def upsert_tool_result_compressor(
    db: AsyncSession,
    *,
    tool_name: str,
    strategy: str,
    config: dict[str, Any] | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    normalized_tool_name = str(tool_name or "").strip()
    if not normalized_tool_name:
        raise ValueError("tool_name is required")
    normalized_strategy = str(strategy or "").strip()
    if not is_supported_strategy(normalized_strategy):
        raise ValueError(f"Unsupported compression strategy: {normalized_strategy}")
    row = (
        await db.execute(select(ToolResultCompressor).where(ToolResultCompressor.tool_name == normalized_tool_name))
    ).scalar_one_or_none()
    payload_config = dict(config or {})
    if row is None:
        row = ToolResultCompressor(
            id=str(uuid.uuid4()),
            tool_name=normalized_tool_name,
            strategy=normalized_strategy,
            config=payload_config,
            is_active=bool(is_active),
        )
        db.add(row)
    else:
        row.strategy = normalized_strategy
        row.config = payload_config
        row.is_active = bool(is_active)
    await db.commit()
    await db.refresh(row)
    return _serialize_compressor(row)


async def list_tool_result_compression_logs(
    db: AsyncSession,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    capped_limit = max(1, min(int(limit or 20), 100))
    rows = (
        (
            await db.execute(
                select(ToolResultCompressionLog).order_by(desc(ToolResultCompressionLog.created_at)).limit(capped_limit)
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_compression_log(row) for row in rows]


async def compress_tool_result_for_model(
    db: AsyncSession,
    *,
    session_id: str,
    tool_name: str,
    result: dict[str, Any],
    request_id: str | None = None,
    fallback: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        compact = fallback(tool_name, result) if fallback else {"value": result}
        compact = enforce_compact_result_budget(
            compact,
            token_budget=compact_result_token_budget(compact, default=MAX_COMPACT_RESULT_TOKENS),
        )
        return compact if isinstance(compact, dict) else {"value": compact}

    row = (
        await db.execute(select(ToolResultCompressor).where(ToolResultCompressor.tool_name == tool_name))
    ).scalar_one_or_none()

    strategy = None
    config: dict[str, Any] = {}
    compressor_id: str | None = None
    if row is not None and row.is_active:
        strategy = row.strategy
        config = dict(row.config or {}) if isinstance(row.config, dict) else {}
        compressor_id = row.id
    elif row is None:
        seed_definition = await get_effective_default_compressor_definition(
            db,
            defaults=DEFAULT_COMPRESSORS,
            tool_name=tool_name,
        )
        if seed_definition and seed_definition.get("is_active", True):
            strategy = str(seed_definition["strategy"])
            config = dict(seed_definition.get("config") or {})
    compressed: dict[str, Any] | None = None
    if strategy:
        handler = get_strategy_handler(strategy)
        if handler is not None:
            compressed = handler(result, config)
    if compressed is None:
        compressed = fallback(tool_name, result) if fallback else result
        strategy_name = strategy or "fallback"
    else:
        strategy_name = strategy
    compressed = enforce_compact_result_budget(
        compressed,
        token_budget=compact_result_token_budget(compressed, default=MAX_COMPACT_RESULT_TOKENS),
    )
    if not isinstance(compressed, dict):
        compressed = {"value": compressed}
    compressed = attach_evidence_contract(
        tool_name=tool_name,
        original_result=result,
        compressed_result=compressed,
        strategy=strategy_name,
    )

    original_tokens = _estimate_tokens(result)
    compressed_tokens = _estimate_tokens(compressed)
    ratio = max(0, min(100, int(round((1 - (compressed_tokens / max(original_tokens, 1))) * 100))))
    db.add(
        ToolResultCompressionLog(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name=tool_name,
            compressor_id=compressor_id,
            strategy=strategy_name,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=ratio,
            request_id=(request_id or "").strip() or None,
        )
    )
    await db.flush()
    return compressed


__all__ = [
    "DEFAULT_COMPRESSORS",
    "MAX_COMPACT_RESULT_TOKENS",
    "compress_tool_result_for_model",
    "ensure_default_tool_result_compressors",
    "list_tool_result_compression_logs",
    "list_tool_result_compressors",
    "upsert_tool_result_compressor",
]
