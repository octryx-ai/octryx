"""The one redactor for subprocess output that is kept as a product result. Output kept as a result passes through here
first."""

from __future__ import annotations

import re
from typing import Any

from .redaction_policy import REDACTED_SECRET, redact_secret_text

# ``scheme://userinfo@``: the userinfo is everything up to the first ``@`` that comes before
# the next ``/``, whitespace or quote, so ``https://host/a@b`` (an ``@`` in the path) is kept.
_URL_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]{0,31}://)[^\s/@'\"<>]+@")
_TOKEN_SHAPED_RE = re.compile(
    r"\b(?:"
    r"gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|glpat-[A-Za-z0-9_-]{16,}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"
    r"|sk-[A-Za-z0-9_-]{16,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r")"
)


def redact_process_output(value: Any, *, max_chars: int | None = None) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = "" if value is None else str(value)
    text = _URL_USERINFO_RE.sub(lambda match: f"{match.group(1)}{REDACTED_SECRET}@", text)
    text = _TOKEN_SHAPED_RE.sub(REDACTED_SECRET, text)
    # ``redact_secret_text`` strips surrounding whitespace; output keeps its own.
    core = text.strip()
    if core:
        start = len(text) - len(text.lstrip())
        text = f"{text[:start]}{redact_secret_text(core)}{text[start + len(core):]}"
    if max_chars is not None and len(text) > max_chars:
        return f"{text[:max_chars]}...[truncated]"
    return text


__all__ = ["redact_process_output"]
