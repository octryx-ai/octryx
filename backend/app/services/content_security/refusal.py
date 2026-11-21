"""A content refusal of a model call, and the turn failure class it gives.

A content policy that refuses a model request (a shipped platform policy at the model-call boundary, or a
published custom policy on the governed gateway route) is a permanent refusal of that content, not a transient
runtime error: the same prompt or tool result is refused again on every rerun. The boundary raises
:class:`ContentPolicyRefusedError` (runtime class ``content_policy_denied``, so the runtime chain never falls back
to another target); the gateway driver raises its own ``LiteLLMGatewayError`` with the same runtime class.

A turn that failed on such a refusal records the closed class :data:`TURN_ERROR_CONTENT_BLOCKED` under
:data:`TURN_ERROR_CLASS_KEY` on the failed trace's ``raw_output``. The class is read from typed facts only (the
exception's runtime class, or the runtime attempts it carries), never from the error text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...agent.core.runtime.runtime_errors import RUNTIME_ERROR_CONTENT_POLICY_DENIED, ProviderRuntimeError

TURN_ERROR_CLASS_KEY = "error_class"
TURN_ERROR_CONTENT_BLOCKED = "content_blocked"
TURN_ERROR_CLASSES = frozenset({TURN_ERROR_CONTENT_BLOCKED})


class ContentPolicyRefusedError(ProviderRuntimeError):
    """A shipped platform content policy refused the model request before it was sent."""

    def __init__(self, policies: tuple[str, ...], content_notice: Mapping[str, Any]) -> None:
        self.policies = tuple(policies)
        self.content_notice = dict(content_notice)
        super().__init__("Content policy refused the request: " + ", ".join(self.policies),
                         error_class=RUNTIME_ERROR_CONTENT_POLICY_DENIED)


def _refused(value: Any) -> bool:
    return getattr(value, "runtime_error_class", None) == RUNTIME_ERROR_CONTENT_POLICY_DENIED


def turn_error_class(exc: BaseException | None) -> str | None:
    """``content_blocked`` when the exception, or a runtime attempt it carries, is a content refusal."""
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
    """``raw_output`` of a failed turn's trace, with the exception's closed class when it has one."""
    error_class = turn_error_class(exc)
    return {**raw_output, TURN_ERROR_CLASS_KEY: error_class} if error_class else raw_output


def recorded_turn_error_class(raw_output: Any) -> str | None:
    """The closed class a failed trace recorded (``raw_output.error`` and a known class), else ``None``."""
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
