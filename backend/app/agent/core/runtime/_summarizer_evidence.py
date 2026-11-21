"""Deterministic evidence-reference helpers for the rolling session summarizer.

The summarizer hands the LLM a compact list of evidence references (real
message ids and tool call ids) so the produced summary can point back to full
information with markers like ``[msg:<id>]`` or ``[tool_call:<id>]``. This
module keeps collection and validation deterministic and reuses the reference
vocabulary established by ``app.services.context_compaction``.
"""

from __future__ import annotations

import re
from typing import Any

from ....services.context_compaction import (
    MAX_EVIDENCE_REFS,
    _iter_tool_call_refs,
    _iter_tool_result_refs,
)
from ....services.prompt_catalog import render_prompt

MAX_EVIDENCE_EXCERPT_CHARS = 120

REFERENCE_MARKER_PATTERN = re.compile(r"\[((?:msg|tool_call):[A-Za-z0-9_.:-]+)\]")


def _evidence_excerpt(value: Any, *, limit: int = MAX_EVIDENCE_EXCERPT_CHARS) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def collect_evidence_from_messages(messages: list) -> list[dict[str, str]]:
    """Collect up to MAX_EVIDENCE_REFS references from persisted Message rows.

    Only real message ids and tool call ids are used; nothing is synthesised,
    so every returned ``ref`` can be resolved later by the drill-back tool.
    """
    refs: list[dict[str, str]] = []
    seen: set[str] = set()

    def _append(ref: str, role: str, tool_name: str, excerpt: str) -> None:
        if not ref or ref in seen or len(refs) >= MAX_EVIDENCE_REFS:
            return
        seen.add(ref)
        refs.append({"ref": ref, "role": role, "tool_name": tool_name, "excerpt": excerpt})

    for message in messages:
        message_id = str(getattr(message, "id", "") or "").strip()
        role = str(getattr(message, "role", "") or "").strip()
        excerpt = _evidence_excerpt(getattr(message, "content", "") or "")
        if message_id and excerpt:
            _append(f"msg:{message_id}", role, "", excerpt)
        for tool_name, tool_call_id in _iter_tool_call_refs(getattr(message, "tool_calls", None)):
            if tool_call_id:
                _append(f"tool_call:{tool_call_id}", role, tool_name, "")
            elif message_id:
                _append(f"msg:{message_id}", role, tool_name, excerpt)
        for tool_name, tool_call_id in _iter_tool_result_refs(getattr(message, "tool_results", None)):
            if tool_call_id:
                _append(f"tool_call:{tool_call_id}", role, tool_name, "")
    return refs


def parse_reference_markers(text: str) -> list[str]:
    """Extract unique reference markers like msg:<id> from a model response."""
    markers: list[str] = []
    for match in REFERENCE_MARKER_PATTERN.finditer(str(text or "")):
        marker = match.group(1)
        if marker not in markers:
            markers.append(marker)
    return markers


def validate_reference_markers(markers: list[str], evidence_refs: list[dict]) -> list[str]:
    """Keep only markers that point at collected evidence (drop hallucinated ids)."""
    known = {str(item.get("ref") or "") for item in evidence_refs if isinstance(item, dict)}
    return [marker for marker in markers if marker in known]


def strip_reference_markers(text: str, valid_refs: set[str]) -> str:
    """Remove markers that are not in valid_refs from free text."""

    def _replace(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1) in valid_refs else ""

    cleaned = REFERENCE_MARKER_PATTERN.sub(_replace, str(text or ""))
    return " ".join(cleaned.split())


def render_evidence_prompt_block(evidence_refs: list[dict]) -> str:
    """Render collected evidence references as a compact prompt block."""
    if not evidence_refs:
        return ""
    lines: list[str] = []
    for item in evidence_refs:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or "").strip()
        if not ref:
            continue
        line = f"[{ref}] role={str(item.get('role') or 'unknown')}"
        tool_name = str(item.get("tool_name") or "").strip()
        if tool_name:
            line += f" tool={tool_name}"
        excerpt = str(item.get("excerpt") or "").strip()
        if excerpt:
            line += f' excerpt="{excerpt}"'
        lines.append(line)
    if not lines:
        return ""
    return render_prompt("context.summarizer.evidence_block", reference_lines="\n".join(lines))
