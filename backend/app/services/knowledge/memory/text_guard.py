"""What may become a memory text: bounded, visible characters, and never a secret.

The secret check reuses the shared redaction policy (``services/redaction_policy``): a text the
redactor would change carries a credential URL, an auth header or token, a ``password=``-style
assignment or a private key block. Its substring prefix heuristic (``looks_like_secret_value``) is
deliberately not used, because "risk-based" or "task-list" contain ``sk-``; the vendor token prefixes
are matched here as whole tokens with a realistic length instead. A secret is refused, not redacted:
a redacted memory would silently say something other than what the user stated.
"""

from __future__ import annotations

import hashlib
import re

from ....models.project.knowledge_memory import MAX_MEMORY_TEXT_CHARS
from ...redaction_policy import SENSITIVE_VALUE_PREFIXES, redact_secret_text
from ..text_safety import has_unsafe_chars
from .errors import MemoryRefusedError

_TOKEN_PREFIXES = tuple(prefix for prefix in SENSITIVE_VALUE_PREFIXES if not prefix.endswith(" "))
_VENDOR_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:" + "|".join(re.escape(prefix) for prefix in _TOKEN_PREFIXES) + r")[A-Za-z0-9_-]{16,}",
    re.IGNORECASE,
)
_AWS_ACCESS_KEY_ID = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")
_WHITESPACE = re.compile(r"\s+")


def contains_secret(text: str) -> bool:
    return (
        redact_secret_text(text) != text.strip()
        or bool(_VENDOR_TOKEN.search(text))
        or bool(_AWS_ACCESS_KEY_ID.search(text))
    )


def normalize_memory_text(raw: object) -> str:
    """The stored form of one memory text, or a fixed refusal."""
    if type(raw) is not str:
        raise MemoryRefusedError("invalid_text")
    text = raw.strip()
    if not text or len(text) > MAX_MEMORY_TEXT_CHARS or has_unsafe_chars(text, allow_line_breaks=True):
        raise MemoryRefusedError("invalid_text")
    if contains_secret(text):
        raise MemoryRefusedError("secret_detected")
    return text


def content_hash(text: str) -> str:
    """Identity of a statement for consolidation: case and whitespace do not make a new memory."""
    canonical = _WHITESPACE.sub(" ", text.casefold()).strip()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["contains_secret", "content_hash", "normalize_memory_text"]
