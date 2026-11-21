"""XML-safe text helpers shared by the AWS topology diagram renderers."""

from __future__ import annotations

import html
import re


def _safe_cell_id(value: str, *, fallback: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("_.-")
    if not safe or safe in {"0", "1"}:
        return fallback
    return safe


def _truncate_label(value: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


def _xml_value(value: str) -> str:
    return html.escape(str(value or ""), quote=True)
