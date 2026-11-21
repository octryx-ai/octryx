"""Opaque references for people in server logs.

Caller display names, enrolled speaker names and Teams user ids identify a person; server logs
carry an opaque reference instead. The reference is an HMAC of the value under a key created once
per process, so the same person keeps the same reference across the log lines of a running
process (enough to follow one call), while the reference cannot be reversed or matched against a
list of names, and it changes on restart.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PROCESS_KEY = secrets.token_bytes(32)
NO_PERSON = "person-none"


def person_log_ref(value: object) -> str:
    """``person-<12 hex>`` for a non-empty value, ``person-none`` otherwise."""
    text = str(value or "").strip()
    if not text:
        return NO_PERSON
    digest = hmac.new(_PROCESS_KEY, text.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"person-{digest[:12]}"
