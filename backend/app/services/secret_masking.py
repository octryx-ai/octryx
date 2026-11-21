"""What a model wrote is stored and shown masked; a value that must run again is kept only sealed (encrypted).

Without masking, a confirmed write plan's preview holds the model-written fields in plain text in the database,
such as an ``sk-...`` token in a request body, and the same values reach the approval reason, the REST call audit,
``tool_calls.parameters`` and run events. Transcripts already pass one rule set
(``backend/scripts/transcript_secrets.py``, via ``session_transcripts.redaction``); every store of model-written
arguments passes the same one.

A confirmed write plan is replayed: the restarted turn performs its writes with the confirmed fields, and a field
the call leaves out is filled from the plan (``chat_write_plan_match``). So the plan keeps the real fields, but only
sealed with the platform's secret key (:data:`SEALED_KEY`, ``secret.service.encrypt_secret``), next to the masked
ones it shows. The model sees the masked value too; a call that passes it back gets the real one put in at the plan
check (:func:`restore_masked_values`), so a write runs with what the person confirmed and nothing is stored in clear.
"""

from __future__ import annotations

import copy
import json
from typing import Any

SEALED_KEY = "sealed_fields"


def masked(value: Any) -> Any:
    """``value`` without secret values (structure, numbers and flags stay); the caller's object is not changed."""
    from .session_transcripts.redaction import redact_entry

    return redact_entry(copy.deepcopy(value))


def masked_text(text: str | None) -> str | None:
    if not text:
        return text
    from .session_transcripts.redaction import redact_text

    return redact_text(text)


def mask_payload(value: Any) -> Any:
    """A stored payload masked everywhere except its sealed parts, which are ciphertext already."""
    if isinstance(value, dict):
        return {key: (item if key == SEALED_KEY else mask_payload(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_payload(item) for item in value]
    return masked(value)


def sealed_fields(fields: dict[str, Any] | None) -> dict[str, Any]:
    """``{"fields": masked}`` plus, when masking changed anything, the real fields sealed under :data:`SEALED_KEY`."""
    from .secret.service import encrypt_secret

    real = dict(fields or {})
    shown = masked(real)
    if shown == real:
        return {"fields": real}
    return {"fields": shown, SEALED_KEY: encrypt_secret(json.dumps(real, ensure_ascii=False, default=str))}


def real_fields(entry: dict[str, Any] | None) -> dict[str, Any]:
    """The fields a confirmed write runs with: the sealed real ones, else the stored ones (nothing was masked)."""
    entry = entry if isinstance(entry, dict) else {}
    sealed = entry.get(SEALED_KEY)
    if isinstance(sealed, str) and sealed:
        from .secret.service import decrypt_secret

        try:
            value = json.loads(decrypt_secret(sealed))
        except Exception:  # noqa: BLE001 - an unreadable seal never runs a write with the masked text
            return {}
        if isinstance(value, dict):
            return value
    return dict(entry.get("fields") or {})


def restore_masked_values(params: dict[str, Any], entry: dict[str, Any]) -> None:
    """Put the real value back for each field the call passed exactly as the plan showed it (masked)."""
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
    """The parts of ``value`` the rule set replaced: ``shown`` is ``value`` with each such part as a marker, so the
    text between markers is literal and pins every replaced span exactly (no character alignment guessing)."""
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
    """The secret parts of a call's arguments: whole values under a secret-like name, or the spans the rule set
    replaces inside a text (``Bearer sk-...`` -> ``sk-...``); at least 6 characters, longest first."""
    found: set[str] = set()
    for key, value in _leaves(arguments):
        shown = masked({key: value} if key else value)
        shown = shown.get(key) if isinstance(shown, dict) else shown
        if not isinstance(shown, str) or shown == value:
            continue
        found.update(span.strip() for span in _redacted_spans(value, shown) if len(span.strip()) >= 6)
    return sorted(found, key=len, reverse=True)


def mask_echoed_arguments(result: Any, arguments: Any) -> Any:
    """``result`` with every secret part of the call's own arguments replaced (a REST call's result may echo the token
    its body carried, back to the model and into ``tool_calls.result``). Other data stays."""
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
