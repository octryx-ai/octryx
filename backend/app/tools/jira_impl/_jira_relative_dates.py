"""Policy helpers for Jira relative release-date parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class RelativeDateRule:
    pattern: re.Pattern[str]
    day_multiplier: int = 1
    direct_days: int | None = None


RELATIVE_DATE_RULES: tuple[RelativeDateRule, ...] = (
    RelativeDateRule(re.compile(r"\bin\s+(\d+)\s+weeks?\b", re.IGNORECASE), day_multiplier=7),
    RelativeDateRule(re.compile(r"\bin\s+(\d+)\s+days?\b", re.IGNORECASE), day_multiplier=1),
    RelativeDateRule(re.compile(r"\btomorrow\b", re.IGNORECASE), direct_days=1),
    RelativeDateRule(re.compile(r"\bnext week\b", re.IGNORECASE), direct_days=7),
)


def infer_relative_release_date_from_message(message: str, *, today: date) -> str:
    normalized_message = str(message or "").strip().lower()
    if not normalized_message:
        return ""

    for rule in RELATIVE_DATE_RULES:
        match = rule.pattern.search(normalized_message)
        if not match:
            continue
        if rule.direct_days is not None:
            return (today + timedelta(days=rule.direct_days)).isoformat()
        if match.lastindex:
            return (today + timedelta(days=int(match.group(1)) * rule.day_multiplier)).isoformat()
    return ""
