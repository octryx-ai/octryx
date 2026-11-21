"""Final-answer cleanup when the turn answers from a source-evidence final prompt."""

from __future__ import annotations

import re
from typing import Any

from ....services.response_guard_policy import (
    EVIDENCE_SOURCE_LABEL_LINE_PATTERN,
    KNOWLEDGE_USER_EVIDENCE_LINE_PATTERN,
    NEGATIVE_KNOWLEDGE_AUTHORSHIP_LINE_PATTERN,
)

_SOURCE_EVIDENCE_FINAL_PROMPT_MARKER = "[source_evidence_final_answer]"
_EMAIL_REDACTION_LINE_PATTERN = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?.*\bemail\b.*(?:redact|privacy|private|not disclosed|not required|security).*$"
)


def _has_source_evidence_final_prompt(request_messages: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(message, dict)
        and str(message.get("role") or "") == "system"
        and _SOURCE_EVIDENCE_FINAL_PROMPT_MARKER in str(message.get("content") or "")
        for message in request_messages or []
    )


def _source_evidence_final_prompt_content(request_messages: list[dict[str, Any]] | None) -> str:
    for message in request_messages or []:
        if not isinstance(message, dict) or str(message.get("role") or "") != "system":
            continue
        content = str(message.get("content") or "")
        if _SOURCE_EVIDENCE_FINAL_PROMPT_MARKER in content:
            return content
    return ""


def _extract_knowledge_user_activity_bullet(prompt_content: str) -> str:
    text = str(prompt_content or "")
    if not text:
        return ""
    total_match = KNOWLEDGE_USER_EVIDENCE_LINE_PATTERN.search(text)
    if total_match is None:
        return ""
    source_match = EVIDENCE_SOURCE_LABEL_LINE_PATTERN.search(text)
    source_text = source_match.group(1).strip() if source_match else ""
    distribution = f", with source distribution {source_text}" if source_text else ""
    return (
        f"- **Knowledge Base activity**: `knowledge_search_by_user` / `source_people` found "
        f"{total_match.group(1)} Knowledge entries linked to the requested person{distribution}. "
        "This is the broad synced user-activity rollup; narrower live connector searches do not replace it."
    )


def _ensure_knowledge_user_activity_in_final_answer(content: str, prompt_content: str) -> str:
    bullet = _extract_knowledge_user_activity_bullet(prompt_content)
    if not bullet:
        return content
    normalized_content = str(content or "")
    if re.search(r"\bKnowledge Base activity\b|\bKnowledge-base user evidence\b|\bsource_people\b", normalized_content):
        return normalized_content
    heading_match = re.search(r"(?im)^##\s+Confirmed evidence\s*$", normalized_content)
    if heading_match is None:
        return f"{bullet}\n\n{normalized_content}".strip()
    insert_at = heading_match.end()
    return f"{normalized_content[:insert_at]}\n\n{bullet}{normalized_content[insert_at:]}".strip()


def _clarify_narrow_confluence_lines_when_knowledge_activity_exists(content: str) -> str:
    text = str(content or "")
    if "Knowledge Base activity" not in text or not re.search(r"\bconfluence:\s*\d+", text, flags=re.IGNORECASE):
        return text
    replacement = (
        "- **Live Confluence check**: direct Confluence CQL returned limited current page examples; "
        "the broader synced Knowledge Base activity above is the Confluence coverage signal for this person."
    )
    return re.sub(
        r"(?im)^\s*-\s*\*\*Confluence(?: contributor)?\*\*:.*(?:at least one|one page|at least 2|2 pages?).*$",
        replacement,
        text,
    )


def _sanitize_source_evidence_final_answer(
    content: str,
    *,
    request_messages: list[dict[str, Any]] | None = None,
) -> str:
    sanitized = _EMAIL_REDACTION_LINE_PATTERN.sub("", str(content or ""))
    sanitized_lines: list[str] = []
    knowledge_authorship_rewritten = False
    for line in sanitized.splitlines():
        if NEGATIVE_KNOWLEDGE_AUTHORSHIP_LINE_PATTERN.search(line):
            if not knowledge_authorship_rewritten:
                prefix = re.match(r"^(\s*[-*]\s*)", line)
                bullet = prefix.group(1) if prefix else "- "
                sanitized_lines.append(
                    f"{bullet}**Knowledge search**: No direct Knowledge entries matched the resolved name/alias "
                    "search in the retrieved evidence."
                )
                knowledge_authorship_rewritten = True
            continue
        sanitized_lines.append(line)
    sanitized = "\n".join(sanitized_lines)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    sanitized = _ensure_knowledge_user_activity_in_final_answer(
        sanitized,
        _source_evidence_final_prompt_content(request_messages),
    )
    sanitized = _clarify_narrow_confluence_lines_when_knowledge_activity_exists(sanitized)
    return sanitized.strip()


__all__ = ["_has_source_evidence_final_prompt", "_sanitize_source_evidence_final_answer"]
