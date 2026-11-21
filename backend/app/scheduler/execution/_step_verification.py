from __future__ import annotations

from typing import Any

_VERIFICATION_FAILURE_MARKERS = ("❌", "failed", "incorrect", "error", "fix required", "wrong")
_VERIFICATION_SUCCESS_MARKERS = ("✅", "passed", "verified", "correct", "success", "approved", "lgtm")


def build_verification_prompt(base_prompt: str, attempt: int, max_attempts: int) -> str:
    """Prefix retry attempts without changing the underlying step prompt."""
    if attempt <= 0:
        return base_prompt
    return f"[Fix attempt {attempt}/{max_attempts}]\n\n{base_prompt}"


def classify_verification_response(result_payload: dict[str, Any]) -> tuple[bool, bool]:
    """Return (passed, failed) markers for a verification agent response."""
    response = str(result_payload.get("response") or "").lower()
    failed = any(marker in response for marker in _VERIFICATION_FAILURE_MARKERS)
    passed = any(marker in response for marker in _VERIFICATION_SUCCESS_MARKERS)
    return passed, failed
