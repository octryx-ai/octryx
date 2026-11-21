from __future__ import annotations

import re
from typing import Any

from ...models import ToolResultCompressionLog, ToolResultCompressor
from ..token_estimation import estimate_serialized_tokens


def _serialize_compressor(row: ToolResultCompressor) -> dict[str, Any]:
    return {
        "id": row.id,
        "tool_name": row.tool_name,
        "strategy": row.strategy,
        "config": dict(row.config or {}) if isinstance(row.config, dict) else {},
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_compression_log(row: ToolResultCompressionLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "tool_name": row.tool_name,
        "compressor_id": row.compressor_id,
        "strategy": row.strategy,
        "original_tokens": row.original_tokens,
        "compressed_tokens": row.compressed_tokens,
        "compression_ratio": row.compression_ratio,
        "request_id": row.request_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _estimate_tokens(value: Any) -> int:
    return estimate_serialized_tokens(value)


def _strip_html(value: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", str(value or ""), flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</h[1-6]\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.I)
    text = re.sub(r"&amp;", "&", text, flags=re.I)
    text = re.sub(r"&lt;", "<", text, flags=re.I)
    text = re.sub(r"&gt;", ">", text, flags=re.I)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_html_headings(value: str, *, max_headings: int) -> list[str]:
    headings = re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", str(value or ""), flags=re.I | re.S)
    normalized: list[str] = []
    for heading in headings:
        stripped = _strip_html(heading)
        if stripped:
            normalized.append(stripped)
        if len(normalized) >= max_headings:
            break
    return normalized
