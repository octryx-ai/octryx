"""A short, sanitized cause of a failed gateway request, safe to log and to show."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from ...redaction_policy import REDACTED_SECRET, redact_secret_text
from ..inbound.secret_scan import contains_secret

MAX_BODY_BYTES = 16 * 1024
MAX_DETAIL_CHARS = 300

# Opaque credential-shaped runs that survive the key=value redaction: vendor-prefixed keys, AWS key ids, and
# token-like runs (see ``_opaque``). Model ids such as ``claude-opus-5-5-20260101-v1`` stay readable.
_VENDOR_KEY = re.compile(r"(?i)\b(?:sk|pk|rk|ghp|gho|ghs|ghu|glpat|xox[abpr])[-_][A-Za-z0-9_-]{8,}")
_AWS_KEY_ID = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{12,}")
_RUN = re.compile(r"[A-Za-z0-9+/=_-]{16,}")
_HEX = re.compile(r"[0-9a-fA-F]{20,}")
_SEGMENT_SPLIT = re.compile(r"[-_]")
_MIN_SEGMENT = 16
_ALNUM = re.compile(r"[A-Za-z0-9]{32,}")
_WHITESPACE = re.compile(r"\s+")


def _upstream_text(body: Any) -> str:
    if not isinstance(body, Mapping):
        return ""
    error = body.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        return message if isinstance(message, str) else ""
    if isinstance(error, str):
        return error
    for key in ("detail", "message"):
        value = body.get(key)
        if isinstance(value, str):
            return value
    return ""


def _letters_and_digits(text: str) -> bool:
    return any(ch.isalpha() for ch in text) and any(ch.isdigit() for ch in text)


def _opaque(match: re.Match[str]) -> str:
    run = match.group(0)
    mixed = any(ch.isupper() for ch in run) and any(ch.islower() for ch in run) and any(ch.isdigit() for ch in run)
    long_segment = any(
        len(segment) >= _MIN_SEGMENT and _letters_and_digits(segment) for segment in _SEGMENT_SPLIT.split(run)
    )
    return REDACTED_SECRET if mixed or long_segment or _HEX.search(run) or _ALNUM.search(run) else run


def sanitize_detail(text: str, *, max_chars: int = MAX_DETAIL_CHARS) -> str:
    cleaned = redact_secret_text(text)
    cleaned = _VENDOR_KEY.sub(REDACTED_SECRET, cleaned)
    cleaned = _AWS_KEY_ID.sub(REDACTED_SECRET, cleaned)
    cleaned = _RUN.sub(_opaque, cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    if contains_secret(cleaned):
        return ""
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def upstream_error_detail(raw_body: bytes | None) -> str:
    if not raw_body or len(raw_body) > MAX_BODY_BYTES:
        return ""
    try:
        body = json.loads(raw_body)
    except ValueError:
        return ""
    return sanitize_detail(_upstream_text(body))


__all__ = ["MAX_DETAIL_CHARS", "sanitize_detail", "upstream_error_detail"]
