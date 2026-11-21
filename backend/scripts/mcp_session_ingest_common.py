"""Redaction and size cap of a Claude Code session digest, shared with the octryx-claude launcher.

The launcher builds the digest it posts to ``/sessions/finalize`` with
``ingest_claude_session.build_digest`` and passes it through ``cap_digest`` here; the platform
vendors both files into the launcher package (``services/octryx_client/artifact.py``).

- ``redact`` strips provider keys, bearer/JWT tokens and credential assignments before anything
  leaves the machine, then applies the full transcript rule set (``transcript_secrets.py``).
- ``cap_digest`` redacts and keeps the digest within ``MAX_DIGEST_CHARS``.
"""

from __future__ import annotations

import re
from pathlib import Path

MAX_DIGEST_CHARS = 60_000

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9_\-\.=]{16,})"),
    re.compile(r"(ghp_[A-Za-z0-9]{20,})"),
    re.compile(r"(AKIA[A-Z0-9]{12,})"),
    re.compile(r"(eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"),
    re.compile(
        r"((?:password|passwd|secret|token|api_key)\s*[=:]\s*)([^\s\"']{6,})",
        re.IGNORECASE,
    ),
]


def _transcript_rules():
    """``transcript_secrets`` next to this file: the full rule set with the one shared list of known secret forms
    (``secret_patterns.py``), so the session summary hides what transcripts and job output hide."""
    import importlib.util

    try:
        rules = Path(__file__).with_name("transcript_secrets.py")
        spec = importlib.util.spec_from_file_location("transcript_secrets", rules)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001 - the summary's own shapes still apply, and the platform redacts again
        return None


_RULES = _transcript_rules()


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: m.group(1) + "[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return _RULES.redact_text(text) if _RULES is not None else text


def cap_digest(digest: str) -> str:
    digest = redact(digest)
    if len(digest) > MAX_DIGEST_CHARS:
        half = MAX_DIGEST_CHARS // 2
        digest = digest[:half] + "\n\n[... middle truncated ...]\n\n" + digest[-half:]
    return digest


__all__ = ["MAX_DIGEST_CHARS", "cap_digest", "redact"]
