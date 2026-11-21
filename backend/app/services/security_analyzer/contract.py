"""Shared contracts and normalization helpers for security analyzer service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

DEFAULT_SECURITY_ANALYZER_CHAIN = [
    "exec_policy",
    "secret_access",
    "command_guardrail",
]

AVAILABLE_SECURITY_ANALYZERS: list[dict[str, str]] = [
    {
        "key": "exec_policy",
        "label": "Exec Policy",
        "description": "Applies diagnosis/read-only execution policy and destructive command denies.",
    },
    {
        "key": "secret_access",
        "label": "Secret Access",
        "description": "Flags commands that read likely secrets, environment dumps or decrypted values.",
    },
    {
        "key": "command_guardrail",
        "label": "Content policies on commands",
        "description": "Sends a command with credentials or internal IP addresses (the shipped content policies "
        "marked for commands) for review.",
    },
    {
        "key": "llm_risk",
        "label": "LLM Risk",
        "description": "Scores risky commands with a configured review model and maps the score to allow/review/deny.",
    },
]

_ALLOWED_ANALYZERS = {item["key"] for item in AVAILABLE_SECURITY_ANALYZERS}
# Finding detail marking a read-only (diagnosis) command rule rather than a risk
# verdict; a governed read-only run converts it into a capability refusal.
CAPABILITY_RULE_DETAIL_KEY = "capability_rule"
_RISK_ORDER = {"low": 1, "normal": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class SecurityAnalyzerFinding:
    analyzer: str
    action: str
    risk_level: str
    reason: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer": self.analyzer,
            "action": self.action,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class SecurityAnalysisReport:
    action: str
    risk_level: str
    reason: str
    findings: list[SecurityAnalyzerFinding]
    analyzer_chain: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "findings": [finding.to_dict() for finding in self.findings],
            "analyzer_chain": list(self.analyzer_chain),
        }


def normalize_security_analyzer_chain(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            values: list[str] = []
        else:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = [item.strip() for item in text.split(",")]
            raw_value = parsed
    values: list[str] = []
    if isinstance(raw_value, (list, tuple, set)):
        values = [str(item).strip() for item in raw_value if str(item).strip()]
    normalized: list[str] = []
    for value in values:
        key = value.lower()
        if key not in _ALLOWED_ANALYZERS or key in normalized:
            continue
        normalized.append(key)
    return normalized or list(DEFAULT_SECURITY_ANALYZER_CHAIN)


def list_security_analyzer_options() -> list[dict[str, str]]:
    return [dict(item) for item in AVAILABLE_SECURITY_ANALYZERS]


def _risk_rank(risk_level: str) -> int:
    return _RISK_ORDER.get(str(risk_level or "").strip().lower(), 1)


def _action_rank(action: str) -> int:
    normalized = str(action or "").strip().lower()
    if normalized == "deny":
        return 3
    if normalized == "review":
        return 2
    return 1
