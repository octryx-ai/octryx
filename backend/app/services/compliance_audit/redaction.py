"""Redaction of audit record details before they are stored. Readers see only ``projection.project_details``."""

from __future__ import annotations

from typing import Any

from ..model_gateway.inbound.secret_scan import contains_secret
from ..redaction_policy import is_secret_setting_key, is_sensitive_key, looks_like_secret_value, setting_key_words

REDACTED = "[REDACTED]"
_KEY_FRAGMENTS = ("api_key", "credential", "password", "private_key", "secret", "token")


def is_credential_key(key: str) -> bool:
    # ``signing_key`` or ``xApiKey``: a name ending in "key" is treated as key material; an audit detail loses little.
    words = setting_key_words(key)
    joined = "_".join(words)
    return (is_secret_setting_key(key) or is_sensitive_key(key) or (bool(words) and words[-1] == "key")
            or any(fragment in joined for fragment in _KEY_FRAGMENTS))


def is_credential_value(value: Any) -> bool:
    return isinstance(value, str) and (looks_like_secret_value(value) or contains_secret(value))


def redact_details(details: Any) -> tuple[dict, list[str]]:
    if not isinstance(details, dict) or not details:
        return {}, []
    redacted: list[str] = []
    return _walk(details, "", redacted), redacted


def _walk(value: Any, path: str, redacted: list[str]) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}" if path else name
            if is_credential_key(name):
                clean[name] = REDACTED
                redacted.append(child)
            else:
                clean[name] = _walk(item, child, redacted)
        return clean
    if isinstance(value, (list, tuple)):
        return [_walk(item, f"{path}[{index}]", redacted) for index, item in enumerate(value)]
    if is_credential_value(value):
        redacted.append(path)
        return REDACTED
    return value
