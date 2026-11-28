"""Which tool results count for a connector's circuit breaker."""

from __future__ import annotations

import re
from typing import Any

FAILURE, IGNORED, SUCCESS = "failure", "ignored", "success"
OUR_CATEGORIES = frozenset({"denied_by_policy", "validation_error", "not_configured", "permission_denied",
                            "configuration_error", "invalid_arguments", "refused"})
_OUR_TEXT = re.compile(
    r"denied by [\w\s-]*policy|disabled by the configured|not allowed by|is not configured|no (github|gitlab|"
    r"bitbucket|jira|confluence)? ?(token|credential|connection)|missing (token|credential)|invalid (argument|"
    r"parameter|request)|is required|must be (allowed|one of)|unknown (repository|tool)|repository is required",
    re.IGNORECASE)
_STATUS = re.compile(r"\b(4\d\d|5\d\d)\b")
_CONNECTOR_TEXT = re.compile(r"timed? ?out|timeout|connection (refused|reset|error|aborted)|network|temporar|"
                             r"unavailable|bad gateway|service unavailable|too many requests|rate limit", re.IGNORECASE)


def _status(result: dict[str, Any]) -> int | None:
    for key in ("status_code", "http_status", "status"):
        value = result.get(key)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
        if isinstance(value, str) and value.isdigit() and 100 <= int(value) <= 599:
            return int(value)
    match = _STATUS.search(str(result.get("error") or ""))
    return int(match.group(1)) if match else None


def breaker_outcome(result: Any) -> str:
    if not isinstance(result, dict) or "error" not in result:
        return SUCCESS
    category = str(result.get("error_category") or result.get("category") or "").strip().lower()
    if category in OUR_CATEGORIES or result.get("policy"):
        return IGNORED
    text = str(result.get("error") or "")
    status = _status(result)
    if status is not None and 400 <= status < 500 and status not in (408, 429):
        return IGNORED
    if status is None and not _CONNECTOR_TEXT.search(text) and _OUR_TEXT.search(text):
        return IGNORED
    return FAILURE


__all__ = ["FAILURE", "IGNORED", "SUCCESS", "breaker_outcome"]
