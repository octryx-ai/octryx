"""Known secret forms, redacted wherever they appear, also without a ``name = value`` around them: the one list for
the platform's redaction (``app/services/redaction_policy``), the transcript rules (``transcript_secrets``) and the
launcher, which gets this file vendored into its package like ``transcript_secrets`` (the wheel carries Python files
only, so the list is a Python module and not JSON). A single source prevents redaction rules from drifting.

Each pattern follows the rule of the same id in gitleaks' default rule set (MIT licence, github.com/gitleaks/gitleaks,
config/gitleaks.toml), narrowed to the token itself; the launcher's pinned gitleaks scans with the full set. The
``*-loose`` entries are the transcript rules' older, wider shapes; they stay because over-redaction is accepted and a
narrower list would let a value through that was redacted before. A kebab name such as ``sk-learn-compatible-…`` is
redacted too, on purpose: it has the shape of a key.

Stdlib only, no imports from the platform: the launcher loads it from its vendored copy.
"""

from __future__ import annotations

import re

KNOWN_TOKENS: tuple[tuple[str, str], ...] = (
    ("github-pat", r"\bghp_[0-9A-Za-z]{36}\b"),
    ("github-fine-grained-pat", r"\bgithub_pat_[0-9A-Za-z_]{82}\b"),
    ("github-oauth", r"\bgho_[0-9A-Za-z]{36}\b"),
    ("github-app-token", r"\b(?:ghu|ghs)_[0-9A-Za-z]{36}\b"),
    ("github-refresh-token", r"\bghr_[0-9A-Za-z]{36}\b"),
    ("github-token-loose", r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
    ("gitlab-pat", r"\bglpat-[0-9A-Za-z_-]{20,}"),
    ("slack-bot-token", r"\bxoxb-[0-9]{10,13}-[0-9]{10,13}[0-9A-Za-z-]*\b"),
    ("slack-user-token", r"\bxox[pe](?:-[0-9]{10,13}){3}-[0-9A-Za-z]{28,34}\b"),
    ("slack-token-loose", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("aws-access-token", r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b"),
    ("aws-access-token-loose", r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ("anthropic-api-key", r"\bsk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{80,}\b"),
    ("openai-api-key", r"\bsk-(?:ant-|proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
    ("stripe-access-token", r"\b(?:sk|rk)_(?:test|live|prod)_[0-9A-Za-z]{8,}"),
    ("stripe-restricted-loose", r"\brk_[A-Za-z0-9]{16,}"),
    ("gcp-api-key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
)


def compiled() -> list[re.Pattern[str]]:
    return [re.compile(pattern) for _id, pattern in KNOWN_TOKENS]


__all__ = ["KNOWN_TOKENS", "compiled"]
