"""Secret redaction of an episode summary before it becomes a source.

The shared redaction core (``services/redaction_policy.redact_secret_text``) replaces credential URLs,
auth headers and tokens, ``password=``-style assignments and private-key blocks. On top of it, the
policy's vendor token prefixes are matched as whole tokens of a realistic length, and AWS access key
ids are matched, because a summary may quote them bare. The substring heuristic
``looks_like_secret_value`` is not used: "risk-based" and "task-list" contain ``sk-``.

A summary is redacted rather than refused: it is a long text written by an agent, and one quoted token
should not discard what the session learned. The number of redactions is reported to the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...redaction_policy import REDACTED_SECRET, SENSITIVE_VALUE_PREFIXES, redact_secret_text

_TOKEN_PREFIXES = tuple(prefix for prefix in SENSITIVE_VALUE_PREFIXES if not prefix.endswith(" "))
_VENDOR_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:" + "|".join(re.escape(prefix) for prefix in _TOKEN_PREFIXES) + r")[A-Za-z0-9_-]{16,}",
    re.IGNORECASE,
)
_AWS_ACCESS_KEY_ID = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")


@dataclass(frozen=True, slots=True)
class RedactedText:
    text: str
    redactions: int


def redact_episode_text(text: str) -> RedactedText:
    before = text.count(REDACTED_SECRET)
    redacted = redact_secret_text(text)
    redacted = _VENDOR_TOKEN.sub(REDACTED_SECRET, redacted)
    redacted = _AWS_ACCESS_KEY_ID.sub(REDACTED_SECRET, redacted)
    return RedactedText(redacted, max(0, redacted.count(REDACTED_SECRET) - before))


__all__ = ["RedactedText", "redact_episode_text"]
