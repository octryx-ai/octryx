"""Deterministic runtime context compaction for long-running sessions."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Message, RuntimeContextCompaction
from ..time_utils import utc_now
from .prompt_catalog import render_prompt

ACTIVE_STATUS = "active"
SUPERSEDED_STATUS = "superseded"
DEFAULT_RECENT_WINDOW = 12
DEFAULT_MIN_SOURCE_MESSAGES = 8
MAX_EXCERPT_CHARS = 240
MAX_SUMMARY_CHARS = 4000
MAX_EVIDENCE_REFS = 30


async def get_latest_context_compaction(
    db: AsyncSession,
    *,
    session_id: str | None,
) -> RuntimeContextCompaction | None:
    if not session_id:
        return None
    result = await db.execute(
        select(RuntimeContextCompaction)
        .where(
            RuntimeContextCompaction.session_id == session_id,
            RuntimeContextCompaction.status == ACTIVE_STATUS,
        )
        .order_by(RuntimeContextCompaction.compaction_index.desc(), RuntimeContextCompaction.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def ensure_session_context_compaction(
    db: AsyncSession,
    *,
    session_id: str | None,
    messages: list[Message],
    recent_window: int | None = None,
    min_source_messages: int = DEFAULT_MIN_SOURCE_MESSAGES,
) -> RuntimeContextCompaction | None:
    """Create or return the active deterministic compaction for a long session.

    The source window is every persisted message older than the recent context
    window. Recent messages remain available verbatim; the compaction gives the
    model an auditable bridge to older work without injecting the full history.
    """
    if not session_id or not messages:
        return None
    window = _safe_recent_window(recent_window)
    source_messages = messages[:-window] if len(messages) > window else []
    if len(source_messages) < max(1, int(min_source_messages or DEFAULT_MIN_SOURCE_MESSAGES)):
        return await get_latest_context_compaction(db, session_id=session_id)

    source_first_id = str(getattr(source_messages[0], "id", "") or "")
    source_last_id = str(getattr(source_messages[-1], "id", "") or "")
    latest = await get_latest_context_compaction(db, session_id=session_id)
    if latest is not None and latest.source_last_message_id == source_last_id:
        return latest

    next_index = int(getattr(latest, "compaction_index", 0) or 0) + 1 if latest is not None else 1
    if latest is not None:
        latest.status = SUPERSEDED_STATUS
        latest.superseded_at = utc_now()

    summary_text, evidence_refs = _build_compaction_payload(source_messages)
    compaction = RuntimeContextCompaction(
        session_id=session_id,
        status=ACTIVE_STATUS,
        compaction_index=next_index,
        source_first_message_id=source_first_id or None,
        source_last_message_id=source_last_id or None,
        source_message_count=len(source_messages),
        recent_message_count=min(window, len(messages)),
        summary_text=summary_text,
        evidence_refs_json=evidence_refs,
    )
    db.add(compaction)
    await db.flush()
    return compaction


def render_context_compaction_for_prompt(compaction: RuntimeContextCompaction | None) -> str:
    if compaction is None:
        return ""
    evidence_refs = compaction.evidence_refs_json if isinstance(compaction.evidence_refs_json, list) else []
    evidence_lines = []
    for ref in evidence_refs[:10]:
        if not isinstance(ref, dict):
            continue
        ref_type = str(ref.get("type") or "message")
        ref_id = str(ref.get("message_id") or ref.get("tool_call_id") or "").strip()
        label = str(ref.get("label") or ref.get("tool_name") or ref.get("role") or "").strip()
        if ref_id:
            evidence_lines.append(f"  - {ref_type}: {ref_id}" + (f" ({label})" if label else ""))
    evidence_text = (
        "\n".join(evidence_lines) if evidence_lines else render_prompt("context.compaction.no_evidence")
    )
    return render_prompt(
        "context.compaction.section",
        compaction_id=compaction.id,
        compaction_index=compaction.compaction_index,
        source_message_count=compaction.source_message_count,
        source_first_message_id=compaction.source_first_message_id or "unknown",
        source_last_message_id=compaction.source_last_message_id or "unknown",
        recent_message_count=compaction.recent_message_count,
        summary_text=str(compaction.summary_text or "").strip(),
        evidence_text=evidence_text,
    )


def _safe_recent_window(value: int | None) -> int:
    try:
        parsed = int(value or DEFAULT_RECENT_WINDOW)
    except (TypeError, ValueError):
        parsed = DEFAULT_RECENT_WINDOW
    return max(4, min(parsed, 40))


def _build_compaction_payload(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    user_requests: list[str] = []
    assistant_progress: list[str] = []
    tool_counter: Counter[str] = Counter()
    evidence_refs: list[dict[str, Any]] = []

    for message in messages:
        role = str(getattr(message, "role", "") or "").strip()
        content = _compact_text(getattr(message, "content", "") or "")
        message_id = str(getattr(message, "id", "") or "")
        if role == "user" and content:
            user_requests.append(content)
            _append_evidence_ref(evidence_refs, {"type": "message", "message_id": message_id, "role": role})
        elif role == "assistant" and content:
            assistant_progress.append(content)
            _append_evidence_ref(evidence_refs, {"type": "message", "message_id": message_id, "role": role})

        for tool_name, tool_call_id in _iter_tool_call_refs(getattr(message, "tool_calls", None)):
            tool_counter[tool_name] += 1
            _append_evidence_ref(
                evidence_refs,
                {
                    "type": "tool_call",
                    "message_id": message_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                },
            )
        for tool_name, tool_call_id in _iter_tool_result_refs(getattr(message, "tool_results", None)):
            tool_counter[tool_name] += 1
            _append_evidence_ref(
                evidence_refs,
                {
                    "type": "tool_result",
                    "message_id": message_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                },
            )

    lines = [
        f"- Source messages compacted: {len(messages)}",
        f"- User requests: {_join_examples(user_requests)}",
        f"- Assistant progress: {_join_examples(assistant_progress)}",
        f"- Tool activity: {_format_tool_counts(tool_counter)}",
    ]
    return _compact_text("\n".join(lines), limit=MAX_SUMMARY_CHARS), evidence_refs


def _compact_text(value: Any, *, limit: int = MAX_EXCERPT_CHARS) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: max(0, limit - 1)].rstrip()}..."


def _join_examples(values: list[str], *, limit: int = 4) -> str:
    selected = [value for value in values if value][:limit]
    if not selected:
        return "none captured"
    suffix = f"; +{len(values) - len(selected)} more" if len(values) > len(selected) else ""
    return " | ".join(selected) + suffix


def _format_tool_counts(counter: Counter[str]) -> str:
    if not counter:
        return "none captured"
    return ", ".join(f"{name}={count}" for name, count in counter.most_common(12))


def _append_evidence_ref(refs: list[dict[str, Any]], ref: dict[str, Any]) -> None:
    if len(refs) >= MAX_EVIDENCE_REFS:
        return
    if ref not in refs:
        refs.append(ref)


def _iter_tool_call_refs(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    refs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        tool_name = str(function.get("name") or item.get("name") or "").strip()
        tool_call_id = str(item.get("id") or "").strip()
        if tool_name:
            refs.append((tool_name, tool_call_id))
    return refs


def _iter_tool_result_refs(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    refs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or item.get("name") or "").strip()
        tool_call_id = str(item.get("tool_call_id") or item.get("id") or "").strip()
        if tool_name:
            refs.append((tool_name, tool_call_id))
    return refs
