"""A content refusal of a model call, and the turn failure class it gives."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agent.runtime.runtime_errors import RUNTIME_ERROR_CONTENT_POLICY_DENIED, ProviderRuntimeError

TURN_ERROR_CLASS_KEY = "error_class"
TURN_ERROR_CONTENT_BLOCKED = "content_blocked"
TURN_ERROR_CLASSES = frozenset({TURN_ERROR_CONTENT_BLOCKED})


# The turn's class is read from typed facts only, never from the error text.
class ContentPolicyRefusedError(ProviderRuntimeError):
    def __init__(self, policies: tuple[str, ...], content_notice: Mapping[str, Any]) -> None:
        self.policies = tuple(policies)
        self.content_notice = dict(content_notice)
        super().__init__("Content policy refused the request: " + ", ".join(self.policies),
                         error_class=RUNTIME_ERROR_CONTENT_POLICY_DENIED)


def _refused(value: Any) -> bool:
    return getattr(value, "runtime_error_class", None) == RUNTIME_ERROR_CONTENT_POLICY_DENIED


def turn_error_class(exc: BaseException | None) -> str | None:
    if exc is None:
        return None
    if _refused(exc):
        return TURN_ERROR_CONTENT_BLOCKED
    attempts = getattr(exc, "runtime_attempts", None)
    for attempt in attempts if isinstance(attempts, list) else []:
        if isinstance(attempt, Mapping) and attempt.get("error_class") == RUNTIME_ERROR_CONTENT_POLICY_DENIED:
            return TURN_ERROR_CONTENT_BLOCKED
    return None


def with_turn_error_class(raw_output: dict[str, Any], exc: BaseException | None) -> dict[str, Any]:
    error_class = turn_error_class(exc)
    return {**raw_output, TURN_ERROR_CLASS_KEY: error_class} if error_class else raw_output


def recorded_turn_error_class(raw_output: Any) -> str | None:
    if not isinstance(raw_output, dict) or not raw_output.get("error"):
        return None
    value = raw_output.get(TURN_ERROR_CLASS_KEY)
    return value if value in TURN_ERROR_CLASSES else None


__all__ = [
    "TURN_ERROR_CLASSES",
    "TURN_ERROR_CLASS_KEY",
    "TURN_ERROR_CONTENT_BLOCKED",
    "ContentPolicyRefusedError",
    "recorded_turn_error_class",
    "turn_error_class",
    "with_turn_error_class",
]
