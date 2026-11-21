"""Audit, counters, and rate limits for external Knowledge MCP access."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog

MCP_KNOWLEDGE_RATE_LIMIT_MAX_REQUESTS = 60
MCP_KNOWLEDGE_RATE_LIMIT_WINDOW_SECONDS = 60
MCP_KNOWLEDGE_RATE_LIMIT_SCOPE = "mcp.knowledge"

_MCP_KNOWLEDGE_COUNTER: Counter[tuple[str, str]] = Counter()


@dataclass
class _McpRateLimitBucket:
    timestamps: list[float] = field(default_factory=list)

    def prune_and_append(self, now: float, window_seconds: int) -> int:
        cutoff = now - window_seconds
        index = 0
        while index < len(self.timestamps) and self.timestamps[index] < cutoff:
            index += 1
        if index:
            del self.timestamps[:index]
        self.timestamps.append(now)
        return len(self.timestamps)

    def count(self, now: float, window_seconds: int) -> int:
        cutoff = now - window_seconds
        return len([timestamp for timestamp in self.timestamps if timestamp >= cutoff])


_MCP_RATE_LIMIT_BUCKETS: dict[str, _McpRateLimitBucket] = defaultdict(_McpRateLimitBucket)
_MCP_RATE_LIMIT_LOCK = asyncio.Lock()


def record_mcp_knowledge_counter(tool_name: str, status_value: str) -> None:
    tool = str(tool_name or "unknown").strip() or "unknown"
    status_label = str(status_value or "unknown").strip().lower() or "unknown"
    _MCP_KNOWLEDGE_COUNTER[(tool, status_label)] += 1


async def enforce_mcp_knowledge_rate_limit(
    *,
    api_key_id: str | None,
    user_id: str,
    tool_name: str,
) -> None:
    key_subject = str(api_key_id or user_id or "anonymous").strip() or "anonymous"
    bucket_key = f"{key_subject}:{str(tool_name or 'unknown').strip() or 'unknown'}"
    async with _MCP_RATE_LIMIT_LOCK:
        now = monotonic()
        bucket = _MCP_RATE_LIMIT_BUCKETS[bucket_key]
        count = bucket.count(now, MCP_KNOWLEDGE_RATE_LIMIT_WINDOW_SECONDS)
        if count >= MCP_KNOWLEDGE_RATE_LIMIT_MAX_REQUESTS:
            retry_after = max(1, int(MCP_KNOWLEDGE_RATE_LIMIT_WINDOW_SECONDS - (now - bucket.timestamps[0])))
            record_mcp_knowledge_counter(tool_name, "rate_limited")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Knowledge MCP rate limit exceeded. Retry after {retry_after} seconds.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(MCP_KNOWLEDGE_RATE_LIMIT_MAX_REQUESTS),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Window": str(MCP_KNOWLEDGE_RATE_LIMIT_WINDOW_SECONDS),
                },
            )
        bucket.prune_and_append(now, MCP_KNOWLEDGE_RATE_LIMIT_WINDOW_SECONDS)


async def audit_mcp_knowledge_tool_call(
    db: AsyncSession,
    *,
    user_id: str,
    api_key_id: str | None,
    api_key_project_id: str | None,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any] | None = None,
    status_value: str,
    error_detail: str = "",
    transport: str = "http",
    grant_scope: dict[str, Any] | None = None,
) -> None:
    """``grant_scope``: optional OAuth grant scope metadata (no tokens); omitted for other callers."""
    record_mcp_knowledge_counter(tool_name, status_value)
    details = {
        "api_key_id": api_key_id,
        "api_key_project_id": api_key_project_id,
        "transport": transport,
        "tool_name": tool_name,
        "status": status_value,
        "arguments": _sanitize_arguments(arguments),
        "result": _result_metadata(result),
    }
    if error_detail:
        details["error"] = error_detail[:500]
    if grant_scope is not None:
        details["grant_scope"] = grant_scope
    db.add(
        AuditLog(
            user_id=user_id,
            action=f"MCP knowledge tool {tool_name}",
            resource_type="mcp_knowledge",
            resource_id=str(arguments.get("project_id") or api_key_project_id or ""),
            details=details,
        )
    )
    await db.flush()


def clear_mcp_knowledge_observability_state() -> None:
    _MCP_KNOWLEDGE_COUNTER.clear()
    _MCP_RATE_LIMIT_BUCKETS.clear()


def render_mcp_knowledge_metrics() -> list[str]:
    lines = [
        "# HELP octryx_mcp_knowledge_tool_calls_total Knowledge MCP tool calls by tool and status",
        "# TYPE octryx_mcp_knowledge_tool_calls_total counter",
    ]
    for (tool_name, status_value), count in sorted(_MCP_KNOWLEDGE_COUNTER.items()):
        lines.append(
            "octryx_mcp_knowledge_tool_calls_total"
            f'{{tool="{_metric_label(tool_name)}",status="{_metric_label(status_value)}"}} {count}'
        )
    return lines


def _sanitize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "project_id",
        "query",
        "task",
        "repository",
        "layers",
        "categories",
        "semantic",
        "limit",
        "max_items",
        "include_engineering_packs",
        "include_repository_evidence",
        "include_relations",
        "knowledge_id",
        "id",
        "direction",
        "depth",
        "relation_types",
        "detail_level",
    }
    sanitized: dict[str, Any] = {}
    for key in allowed_keys:
        if key not in arguments:
            continue
        value = arguments[key]
        if isinstance(value, str):
            sanitized[key] = value[:300]
        elif isinstance(value, list):
            sanitized[key] = [str(item)[:120] for item in value[:10]]
        elif isinstance(value, bool | int | float) or value is None:
            sanitized[key] = value
        else:
            sanitized[key] = str(value)[:300]
    return sanitized


def _result_metadata(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    items = result.get("items")
    if not isinstance(items, list):
        items = result.get("project_facts") if isinstance(result.get("project_facts"), list) else []
    evidence_count = result.get("evidence_count") or 0
    return {
        "item_count": len(items),
        "unknown_count": len(result.get("unknowns") or []) if isinstance(result.get("unknowns"), list) else 0,
        "evidence_count": int(evidence_count) if str(evidence_count).isdigit() else 0,
        "node_count": len(result.get("nodes") or []) if isinstance(result.get("nodes"), list) else 0,
        "edge_count": len(result.get("edges") or []) if isinstance(result.get("edges"), list) else 0,
    }


def _metric_label(value: str) -> str:
    return str(value or "unknown").replace("\\", "\\\\").replace('"', '\\"')
