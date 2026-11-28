"""Regex PII detection and in-place redaction."""

from __future__ import annotations

import re
from typing import Any

from ...models.security.data_classification import (
    PII_CREDIT_CARD,
    PII_EMAIL,
    PII_IBAN,
    PII_IP_ADDRESS,
    PII_NATIONAL_ID,
    PII_PHONE,
    PII_SSN,
)

# ---------------------------------------------------------------------------
# PII detection patterns
# ---------------------------------------------------------------------------

_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    PII_IP_ADDRESS: re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    ),
    PII_CREDIT_CARD: re.compile(
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b"
    ),
    PII_SSN: re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b"),
    PII_IBAN: re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b"),
    PII_NATIONAL_ID: re.compile(r"\b[A-Z]{1,2}\d{6,9}[A-Z]?\b"),
    PII_EMAIL: re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
    # Phone: international (+XX...) or US-style (NNN-NNN-NNNN) — applied last so it
    # doesn't consume SSN / IP patterns that have already been replaced
    PII_PHONE: re.compile(r"\+[\d\s\-().]{8,18}|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
}

# Replacement masks per PII type
_PII_MASKS: dict[str, str] = {
    PII_EMAIL: "[EMAIL]",
    PII_PHONE: "[PHONE]",
    PII_SSN: "[SSN]",
    PII_CREDIT_CARD: "[CARD]",
    PII_IBAN: "[IBAN]",
    PII_IP_ADDRESS: "[IP]",
    PII_NATIONAL_ID: "[ID]",
}




def pii_redact_text(text: str, *, pii_types: list[str] | None = None) -> tuple[str, list[str]]:
    detected: list[str] = []
    result = text
    active_types = pii_types or list(_PII_PATTERNS.keys())
    for pii_type in active_types:
        pattern = _PII_PATTERNS.get(pii_type)
        if pattern is None:
            continue
        if pattern.search(result):
            detected.append(pii_type)
            result = pattern.sub(_PII_MASKS.get(pii_type, "[REDACTED]"), result)
    return result, detected


def detect_and_redact_pii(
    payload: Any, *, prefix: str = "", pii_types: list[str] | None = None
) -> tuple[Any, list[str], list[str]]:
    detected_set: set[str] = set()
    paths: list[str] = []

    def _process(obj: Any, path: str) -> Any:
        if isinstance(obj, str):
            redacted, found = pii_redact_text(obj, pii_types=pii_types)
            if found:
                detected_set.update(found)
                paths.append(path)
            return redacted
        if isinstance(obj, dict):
            return {k: _process(v, f"{path}.{k}" if path else k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_process(item, f"{path}[{i}]") for i, item in enumerate(obj)]
        return obj

    result = _process(payload, prefix)
    return result, sorted(detected_set), paths
