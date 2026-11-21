"""High-confidence secret detection for the content that enters the model gateway.

A coding agent reads source code all day, and source code is full of *names* of
secrets: ``password = settings.db_password``, ``token: str``, ``f"Bearer {token}"``,
``postgresql://user:${DB_PASSWORD}@db``. The shared redaction policy treats every
``token = ...`` assignment as secret-bearing, which is right for redacting stored
payloads but would refuse ordinary source files at the gateway. This detector refuses
only *values* that are credential material by their own shape:

- a private key block,
- an AWS access key id (``AKIA``/``ASIA`` + 16),
- an AWS secret access key assigned to its well-known name,
- a vendor token with its fixed prefix and a realistic length (GitHub, GitLab, Slack,
  ``sk-`` API keys),
- a JWT (three base64url segments, header starting ``eyJ``),
- a bearer credential of realistic length,
- a URL carrying a literal password (a ``$``/``{``/``<``-led placeholder is not one).

Each hit has a fixed kind; the matched text itself is never returned. :func:`secret_spans` gives the content
detectors (``services/content_detection``, detector ``secrets``) the positions to mask; they stay in memory.
"""

from __future__ import annotations

import re

_BOUNDARY = r"(?<![A-Za-z0-9_-])"

_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    (
        "aws_secret_access_key",
        re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])"),
    ),
    (
        "vendor_token",
        re.compile(
            _BOUNDARY
            + r"(?:ghp_|gho_|ghs_|ghu_|github_pat_|glpat-|xoxb-|xoxp-|xoxa-|sk-)[A-Za-z0-9_-]{20,}"
        ),
    ),
    ("jwt", re.compile(_BOUNDARY + r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{16,}")),
    ("bearer_credential", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{32,}")),
    ("credential_url", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:(?![$<{*])[^@\s/]{6,}@")),
)


def secret_spans(text: str) -> tuple[tuple[str, int, int], ...]:
    """``(kind, start, end)`` of every credential found in ``text``, in text order (positions stay in memory)."""

    if not text:
        return ()
    spans = [(kind, match.start(), match.end()) for kind, pattern in _DETECTORS for match in pattern.finditer(text)]
    return tuple(sorted(spans, key=lambda item: (item[1], -item[2])))


def secret_kinds(text: str) -> tuple[str, ...]:
    """The fixed kinds of credential material found in ``text`` (empty when clean)."""

    if not text:
        return ()
    return tuple(kind for kind, pattern in _DETECTORS if pattern.search(text))


def contains_secret(text: str) -> bool:
    return bool(secret_kinds(text))


__all__ = ["contains_secret", "secret_kinds", "secret_spans"]
