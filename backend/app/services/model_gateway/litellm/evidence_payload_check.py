"""The payload check a qualification evidence file must pass before it is written (``evidence_writer``)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ...redaction_policy import is_sensitive_key, looks_like_secret_value
from .evidence import CALL_EVIDENCE_KEYS
from .evidence_value_shape import has_declared_grammar, is_admissible_evidence_value

EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_KEY = "evidence_payload_sensitive_key"
EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE = "evidence_payload_sensitive_value"
EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_FINITE = "evidence_payload_value_not_finite"
EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_ADMISSIBLE = "evidence_payload_value_not_admissible"

# Gateway evidence records scheme, host and port separately, never a URL, so a ``://`` in any string means
# something unexpected reached the payload.
_URL_FRAGMENT = "://"

_REPORT_EVIDENCE_KEYS = frozenset(
    {
        "qualification",
        "evidence_origin",
        "live_evidence_state",
        "live_evidence_blocking_reason",
        "passed",
        "gate_satisfied",
        "missing_check_codes",
        "gateway",
        "checks",
        "check",
        "status",
        "detail",
    }
)
# The only key names a refusal may echo; anything else is reported without a field name.
ECHOABLE_EVIDENCE_KEYS = frozenset(CALL_EVIDENCE_KEYS) | _REPORT_EVIDENCE_KEYS


def inadmissible_payload(payload: Any, *, key_hint: str = "") -> tuple[str, str]:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            name = str(key)
            if is_sensitive_key(name):
                return EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_KEY, name
            denial, field_name = inadmissible_payload(value, key_hint=name)
            if denial:
                return denial, field_name
        return "", ""
    if isinstance(payload, str):
        if not payload.strip():
            # Empty is legitimate for ``endpoint_base_path`` and the TLS digests under a plaintext loopback policy.
            return "", ""
        if is_admissible_evidence_value(key_hint, payload):
            return "", ""
        if _URL_FRAGMENT in payload or looks_like_secret_value(payload):
            return EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE, key_hint
        if has_declared_grammar(key_hint):
            # Reported apart from a secret-shaped value because the two need different operator action.
            return EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_ADMISSIBLE, key_hint
        return "", ""
    if isinstance(payload, float) and not math.isfinite(payload):
        # ``NaN``/``Infinity`` are not JSON; refusing them keeps the file parseable by a strict reader.
        return EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_FINITE, key_hint
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for item in payload:
            denial, field_name = inadmissible_payload(item, key_hint=key_hint)
            if denial:
                return denial, field_name
    return "", ""


__all__ = [
    "ECHOABLE_EVIDENCE_KEYS",
    "EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_KEY",
    "EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE",
    "EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_ADMISSIBLE",
    "EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_FINITE",
    "inadmissible_payload",
]
