"""Secret values leave a device's job messages before they are buffered or sent.

A pipeline step's ``output_tail``, a hands_on ``error`` or a tool's ``stdout`` is whatever a command printed, and a
test that prints ``DB_PASSWORD=…`` or a stack trace with a token put it on the platform, which redacted it only when
showing it. Now the device redacts every output field of a job message with the transcript rules
(:func:`transcript_redact.redact_text`: ``secret_patterns.py`` plus the assignment, JSON and header rules), before
the outbox writes it to disk. Only output fields are touched: ids, paths, hashes and file payloads stay exact.
The platform still redacts on its side as well.

If the rules cannot be loaded, an output field is replaced as a whole: fail closed, the job itself goes on.
"""

from __future__ import annotations

from typing import Any

#: Keys whose string values are command output (also inside lists and nested dicts).
OUTPUT_KEYS = frozenset({"output_tail", "output", "stdout", "stderr", "error", "traceback", "log_tail"})
UNAVAILABLE = "[redacted: secret rules unavailable on this device]"


def _redactor():
    try:
        from .transcript_redact import redact_text, rules  # noqa: PLC0415

        rules()
        return redact_text
    except Exception:  # noqa: BLE001 - missing rules mean nothing of the output goes out
        return lambda _text: UNAVAILABLE


def _walk(value: Any, redact, inside_output: bool) -> Any:
    if isinstance(value, dict):
        return {key: _walk(item, redact, inside_output or key in OUTPUT_KEYS) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk(item, redact, inside_output) for item in value]
    if inside_output and isinstance(value, str) and value:
        return redact(value)
    return value


def redact_outputs(body: dict[str, Any]) -> dict[str, Any]:
    """``body`` with every output field's text redacted; other fields unchanged."""
    return _walk(body, _redactor(), False)


__all__ = ["OUTPUT_KEYS", "redact_outputs"]
