"""What a model wrote is stored and shown masked; a value that must run again is kept only sealed (encrypted)."""

from __future__ import annotations

import copy
import json
from typing import Any

SEALED_KEY = "sealed_fields"


def masked(value: Any) -> Any:
    # The caller's object is not changed.
    from .session_transcripts.redaction import redact_entry

    return redact_entry(copy.deepcopy(value))


def masked_text(text: str | None) -> str | None:
    if not text:
        return text
    from .session_transcripts.redaction import redact_text

    return redact_text(text)


def mask_payload(value: Any) -> Any:
    # Sealed parts are ciphertext already.
    if isinstance(value, dict):
        return {key: (item if key == SEALED_KEY else mask_payload(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_payload(item) for item in value]
    return masked(value)


def sealed_fields(fields: dict[str, Any] | None) -> dict[str, Any]:
    from .secret.crypto import encrypt_secret

    real = dict(fields or {})
    shown = masked(real)
    if shown == real:
        return {"fields": real}
    return {"fields": shown, SEALED_KEY: encrypt_secret(json.dumps(real, ensure_ascii=False, default=str))}


def real_fields(entry: dict[str, Any] | None) -> dict[str, Any]:
    entry = entry if isinstance(entry, dict) else {}
    sealed = entry.get(SEALED_KEY)
    if isinstance(sealed, str) and sealed:
        from .secret.crypto import decrypt_secret

        try:
            value = json.loads(decrypt_secret(sealed))
        except Exception:  # noqa: BLE001 - an unreadable seal never runs a write with the masked text
            return {}
        if isinstance(value, dict):
            return value
    return dict(entry.get("fields") or {})


def restore_masked_values(params: dict[str, Any], entry: dict[str, Any]) -> None:
    # Only a field passed exactly as the plan showed it (masked) gets its real value back.
    shown = dict(entry.get("fields") or {})
    real = real_fields(entry)
    for name, value in list(params.items()):
        if name in shown and value == shown[name] and real.get(name) != value and name in real:
            params[name] = real[name]


def _leaves(value: Any, key: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(key, value)]
    if isinstance(value, dict):
        return [leaf for name, item in value.items() for leaf in _leaves(item, str(name))]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item, key)]
    return []


def _redacted_spans(value: str, shown: str) -> list[str]:
    import re

    marker = "[redacted]"
    if marker not in shown:
        return [value] if shown != value else []
    pieces = shown.split(marker)
    pattern = "^" + "(.+?)".join(re.escape(piece) for piece in pieces) + "$"
    found = re.match(pattern, value, re.S)
    if found is None:
        return [value]  # the rule set rewrote more than the marked parts: treat the whole value as secret
    return [span for span in found.groups() if span]


def echoed_secrets(arguments: Any) -> list[str]:
    found: set[str] = set()
    for key, value in _leaves(arguments):
        shown = masked({key: value} if key else value)
        shown = shown.get(key) if isinstance(shown, dict) else shown
        if not isinstance(shown, str) or shown == value:
            continue
        found.update(span.strip() for span in _redacted_spans(value, shown) if len(span.strip()) >= 6)
    return sorted(found, key=len, reverse=True)


def mask_echoed_arguments(result: Any, arguments: Any) -> Any:
    # A REST result may echo the token its body carried, back to the model and into ``tool_calls.result``.
    secrets = echoed_secrets(arguments)
    if not secrets:
        return result

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            for secret in secrets:
                value = value.replace(secret, "[redacted]")
            return value
        if isinstance(value, dict):
            return {name: scrub(item) for name, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(result)


__all__ = ["SEALED_KEY", "echoed_secrets", "mask_echoed_arguments", "mask_payload", "masked", "masked_text",
           "real_fields", "restore_masked_values", "sealed_fields"]
