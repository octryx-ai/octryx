"""Text normalization helpers for presentation-oriented Office tools."""

from __future__ import annotations

import re
from typing import Any


def _normalize_presentation_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    text = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _presentation_text_line(value: Any) -> str:
    text = _normalize_presentation_text(str(value or ""))
    text = re.sub(r"^(?:[•\-\*]+\s*|\d+[.)]\s+)", "", text).strip()
    return re.sub(r"\s+", " ", text).strip(" -:")


def _truncate_presentation_text(value: Any, *, max_len: int) -> str:
    text = _presentation_text_line(value)
    if len(text) <= max_len:
        return text
    for separator in (". ", "; ", ", ", " "):
        cut = text.rfind(separator, 0, max_len + 1)
        if cut >= max(12, max_len // 2):
            trimmed = text[: cut + (1 if separator.strip() in {".", ";"} else 0)].strip()
            if trimmed:
                return trimmed
    return text[:max_len].rstrip(" ,;:-") + "..."


def _split_presentation_lines(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        lines: list[str] = []
        for item in value:
            lines.extend(_split_presentation_lines(item))
        return lines
    text = _normalize_presentation_text(str(value or ""))
    if not text:
        return []
    raw_lines = re.split(r"\n+|•|\u2022", text)
    lines: list[str] = []
    for raw_line in raw_lines:
        cleaned = _presentation_text_line(raw_line)
        if cleaned:
            lines.append(cleaned)
    return lines


def _compact_bullet_lines(value: Any, *, max_items: int, max_line_len: int) -> list[str]:
    compacted: list[str] = []
    seen: set[str] = set()
    for line in _split_presentation_lines(value):
        shortened = _truncate_presentation_text(line, max_len=max_line_len)
        key = shortened.lower()
        if shortened and key not in seen:
            seen.add(key)
            compacted.append(shortened)
        if len(compacted) >= max_items:
            break
    return compacted


__all__ = [name for name in vars() if name.startswith("_") and not name.startswith("__")]
