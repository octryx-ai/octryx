"""Lessons learned from this session for the team, the client's side.

After a compaction (``PostCompact``, with Claude Code's own summary) and at the session's end (``SessionEnd``, the
facts only) octryx sends the facts its context manager kept to ``POST /sessions/lessons``. The platform proposes
lessons for the Workspace's team only when that Workspace switched it on; a person with the confirmation right
confirms them (``knowledge/memory/session_lessons`` on the platform).

What leaves the Mac, by design:

- **paths, never file contents:** the facts hold file paths, commands and results, requests and todos; no tool output;
- **secrets out before sending:** :func:`redact` removes private keys, AWS keys, tokens and ``password=…`` from every
  text (the platform redacts again and refuses any candidate that still looks like one);
- **one ``ref`` per compaction or end:** derived from the session and the content, so a hook retry sends the same
  ``ref`` and the platform adds nothing twice;
- **opt-out:** ``octryx-claude context-manager lessons off`` (or ``OCTRYX_SESSION_LESSONS=0``) sends nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from .state import LocalState, read_json

MAX_SUMMARY_CHARS = 8000
_SECRETS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"(?i)(aws_secret_access_key|secret_access_key|aws_session_token)\s*[=:]\s*\S+"),
    re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"),
]


def enabled(state: LocalState) -> bool:
    if os.environ.get("OCTRYX_SESSION_LESSONS", "").strip().lower() in ("0", "off", "false", "no"):
        return False
    return state.config().get("session_lessons") is not False


def redact(value: Any) -> Any:
    """Every string inside ``value`` with secret shapes replaced by ``[redacted]``."""
    if isinstance(value, str):
        for pattern in _SECRETS:
            value = pattern.sub("[redacted]", value)
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def _facts(state: LocalState, hook_input: dict[str, Any]) -> dict[str, Any]:
    """The context manager's facts of this session: kept at the last compaction, else read from the transcript."""
    from . import context_manager  # noqa: PLC0415

    session_id = str(hook_input.get("session_id") or "")
    path = state.root / "context" / f"{session_id}.json"
    if re.match(r"^[A-Za-z0-9_-]{1,80}$", session_id) and path.exists():
        stored = read_json(path)
        if isinstance(stored, dict) and any(stored.values()):
            return stored
    transcript = context_manager.own_transcript(state, hook_input)  # only inside octryx's own config dirs
    try:
        if transcript is not None and transcript.is_file():
            return context_manager.extract(context_manager._tail_lines(transcript))
        return {}
    except OSError:
        return {}


def lessons_body(state: LocalState, hook_input: dict[str, Any], *, kind: str) -> dict[str, Any] | None:
    """The body for ``POST /sessions/lessons``, or ``None`` when off or there is nothing to send."""
    if not enabled(state):
        return None
    facts = _facts(state, hook_input)
    summary = hook_input.get("compact_summary") if kind == "compact" else None
    summary = str(summary)[:MAX_SUMMARY_CHARS] if isinstance(summary, str) and summary.strip() else None
    if not any(facts.values()) and not summary:
        return None
    body = {"facts": redact({key: facts.get(key) for key in ("goal", "requests", "files", "tests", "todos")}),
            "summary": redact(summary) if summary else None}
    digest = hashlib.sha256(json.dumps([str(hook_input.get("session_id") or ""), kind, body], sort_keys=True,
                                       default=str).encode()).hexdigest()
    body["ref"] = f"{kind[:3]}-{digest[:40]}"
    return body


__all__ = ["enabled", "lessons_body", "redact"]
