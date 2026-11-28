"""Secret values leave a device's job messages before they are buffered or sent."""

from __future__ import annotations

from typing import Any

#: Keys whose string values are command output (also inside lists and nested dicts).
OUTPUT_KEYS = frozenset({"output_tail", "output", "stdout", "stderr", "error", "traceback", "log_tail",
                         "report_text", "junit_xml"})
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
    return _walk(body, _redactor(), False)


__all__ = ["OUTPUT_KEYS", "redact_outputs"]
