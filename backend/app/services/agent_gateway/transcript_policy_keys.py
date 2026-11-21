"""The Workspace switch "full session transcripts", ``agent_gateway_policy.session_transcripts``.

``{enabled: bool, retention_days: int}``. Today the platform only gets a session's job events, its live progress
(no file contents), the redacted capped digest at finalize and its usage; the raw Claude Code transcript stays on the
Mac. With ``enabled`` an octryx-claude session of this Workspace uploads its full transcript, subagent transcripts
included, redacted on the Mac and again on the platform (``services/session_transcripts``), for debugging and
analysis. Stored transcripts live ``retention_days`` and are then purged by the workflow sweep's tick.

- ``enabled`` (default **false**, an opt-in): off means nothing changes against today; switching it off stops a
  running session's upload at its next batch (the platform answers ``off``);
- ``retention_days`` (default 30, 1..3650): how long a stored transcript stays readable; a change applies to every
  transcript already stored at the next purge.

Kept free of other imports because ``agent_gateway/policy`` validates it on every admin write.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SESSION_TRANSCRIPTS_KEY = "session_transcripts"
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650
_FIELDS = frozenset({"enabled", "retention_days"})


class TranscriptPolicyError(ValueError):
    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason = reason
        self.path = path


@dataclass(frozen=True, slots=True)
class TranscriptPolicy:
    enabled: bool = False
    retention_days: int = 30

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_TRANSCRIPT_POLICY = TranscriptPolicy()


def normalize_transcript_policy(value: Any, path: str) -> dict[str, Any]:
    """The validated section for storage, all fields filled; raises ``TranscriptPolicyError``."""
    if not isinstance(value, dict):
        raise TranscriptPolicyError("not_an_object", path)
    unknown = sorted(set(value) - _FIELDS)
    if unknown:
        raise TranscriptPolicyError("unknown_field", f"{path}.{unknown[0]}")
    enabled = value.get("enabled", DEFAULT_TRANSCRIPT_POLICY.enabled)
    if type(enabled) is not bool:
        raise TranscriptPolicyError("invalid_flag", f"{path}.enabled")
    days = value.get("retention_days", DEFAULT_TRANSCRIPT_POLICY.retention_days)
    if type(days) is not int or not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
        raise TranscriptPolicyError("invalid_retention_days", f"{path}.retention_days")
    return TranscriptPolicy(enabled=enabled, retention_days=days).as_dict()


def transcript_policy_from_config(config: Any) -> tuple[TranscriptPolicy, str]:
    """``(policy, source)``: the Workspace's stored section (``workspace``) or the default (``default``). A section
    that cannot be read is the default: an unreadable switch never uploads anything."""
    stored = config.get("agent_gateway_policy") if isinstance(config, dict) else None
    section = stored.get(SESSION_TRANSCRIPTS_KEY) if isinstance(stored, dict) else None
    if section is None:
        return DEFAULT_TRANSCRIPT_POLICY, "default"
    try:
        return TranscriptPolicy(**normalize_transcript_policy(section, SESSION_TRANSCRIPTS_KEY)), "workspace"
    except TranscriptPolicyError:
        return DEFAULT_TRANSCRIPT_POLICY, "default"


__all__ = [
    "DEFAULT_TRANSCRIPT_POLICY",
    "MAX_RETENTION_DAYS",
    "MIN_RETENTION_DAYS",
    "SESSION_TRANSCRIPTS_KEY",
    "TranscriptPolicy",
    "TranscriptPolicyError",
    "normalize_transcript_policy",
    "transcript_policy_from_config",
]
