"""Workflow-owned knowledge-evidence salvage for loop ceilings and weak runtimes.

Synthesizes a last-resort answer for the ``knowledge_request`` workflow from
knowledge tool results already collected in the turn.
"""

from __future__ import annotations

import re
from typing import Any

# The governed Knowledge reads. Only ``knowledge_search`` passages feed the salvage answer; a
# ``knowledge_read`` still counts as Knowledge evidence progress for the loop.
KNOWLEDGE_TOOL_NAMES = {
    "knowledge_search",
    "knowledge_read",
}


def _value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _tool_name(item: Any) -> str:
    return str(_value(item, "tool_name") or "").strip()


def _payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    preview = value.get("preview")
    compact_result = preview.get("compact_result") if isinstance(preview, dict) else None
    return compact_result if isinstance(compact_result, dict) else value


def _result(item: Any) -> dict[str, Any]:
    return _payload(_value(item, "result"))


def _brief_text(value: Any, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _add_item(
    items: list[dict[str, str]],
    seen: set[str],
    *,
    title: str,
    content: Any,
    source: str = "",
    max_chars: int,
) -> None:
    normalized_title = str(title or "").strip()
    if not normalized_title:
        return
    identity = normalized_title.lower()
    if identity in seen:
        return
    rendered_content = _brief_text(content, max_chars=max_chars)
    if not rendered_content:
        return
    seen.add(identity)
    items.append({"title": normalized_title, "content": rendered_content, "source": str(source or "").strip()})


def _add_governed_passages(
    items: list[dict[str, str]],
    seen: set[str],
    passages: Any,
    *,
    max_items: int,
    max_chars: int,
) -> None:
    """Passages of a governed ``knowledge_search`` result; the source is the passage's ``cite_as`` link."""
    for passage in passages if isinstance(passages, list) else []:
        if len(items) >= max_items:
            return
        if not isinstance(passage, dict):
            continue
        title = str(passage.get("source_title") or "").strip()
        section = str(passage.get("section") or "").strip()
        _add_item(
            items,
            seen,
            title=f"{title} § {section}" if title and section else title,
            content=passage.get("text"),
            source=str(passage.get("cite_as") or passage.get("source_url") or "").strip(),
            max_chars=max_chars,
        )


def build_knowledge_salvage_answer(
    user_message: str,
    tool_history: list[Any] | tuple[Any, ...],
    *,
    max_items: int = 10,
    content_chars: int = 900,
) -> str:
    """Build a last-resort answer from already collected Knowledge evidence."""

    if not any(_tool_name(item) in KNOWLEDGE_TOOL_NAMES for item in tool_history or []):
        return ""

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    search_count = 0

    # Only the governed ledger search counts.
    for item in tool_history or []:
        if _tool_name(item) != "knowledge_search":
            continue
        result = _result(item)
        if not result or result.get("error"):
            continue
        search_count = max(
            search_count,
            _int_value(result.get("total_matches") or result.get("count") or result.get("result_count")),
        )
        # Cited passages, each with its own source link.
        _add_governed_passages(
            items, seen, result.get("evidence"), max_items=max_items, max_chars=min(content_chars, 420)
        )
        if len(items) >= max_items:
            break

    if not items:
        return ""

    if search_count <= 0:
        search_count = len(items)
    lines = [
        (
            f"I found {search_count} matching Knowledge entries and synthesized this answer from the "
            "evidence already loaded."
        )
    ]
    for item in items:
        lines.append(f"- {item['title']}: {item['content']}")
    sources = [item["source"] for item in items if item.get("source")]
    if sources:
        lines.append("Sources: " + ", ".join(dict.fromkeys(sources[:8])))
    return "\n".join(lines)


__all__ = ["KNOWLEDGE_TOOL_NAMES", "build_knowledge_salvage_answer"]
