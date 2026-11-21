"""Secret-safe provider metadata redaction helpers."""

from __future__ import annotations

from typing import Any

from ..redaction_policy import REDACTED_SECRET, is_sensitive_key, redact_secret_payload

REDACTED_PROVIDER_SECRET = REDACTED_SECRET


def is_provider_sensitive_key(key: str) -> bool:
    return is_sensitive_key(key)


def redact_provider_public_metadata(value: Any, *, key_hint: str = "") -> Any:
    return redact_secret_payload(value, key_hint=key_hint)


def provider_secret_is_configured(*, raw_value: Any = None, secret_ref: Any = None) -> bool:
    return bool(str(raw_value or "").strip()) or bool(str(secret_ref or "").strip())


def provider_public_credential_marker(*, configured: bool) -> str:
    return "********" if configured else ""


__all__ = [
    "REDACTED_PROVIDER_SECRET",
    "is_provider_sensitive_key",
    "provider_public_credential_marker",
    "provider_secret_is_configured",
    "redact_provider_public_metadata",
]
