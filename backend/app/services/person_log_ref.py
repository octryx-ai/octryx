"""Opaque references for people in server logs. An HMAC under a per-process key: stable within a running process
only."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PROCESS_KEY = secrets.token_bytes(32)
NO_PERSON = "person-none"


def person_log_ref(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return NO_PERSON
    digest = hmac.new(_PROCESS_KEY, text.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"person-{digest[:12]}"
