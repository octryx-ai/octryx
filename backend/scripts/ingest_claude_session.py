"""Distill a Claude Code transcript into a plain-text session digest.

``build_digest`` keeps the user asks and the assistant text of a transcript (JSON lines). The
octryx-claude launcher posts it to ``/sessions/finalize`` after ``mcp_session_ingest_common.cap_digest``
redacted and capped it; the platform vendors both files into the launcher package
(``services/octryx_client/artifact.py``).
"""

from __future__ import annotations

import json


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


def build_digest(transcript_path: str) -> str:
    """Distill the conversation: user asks + assistant text (secrets redacted downstream)."""
    lines: list[str] = []
    with open(transcript_path) as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = entry.get("type")
            if kind not in ("user", "assistant"):
                continue
            message = entry.get("message") or {}
            text = _message_text(message).strip()
            if not text or text.startswith("<system-reminder") or "tool_result" in str(message.get("content"))[:40]:
                continue
            role = "USER" if kind == "user" else "ASSISTANT"
            lines.append(f"[{role}] {text}")
    return "\n\n".join(lines)
