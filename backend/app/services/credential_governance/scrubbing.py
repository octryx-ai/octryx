"""Export scrubbing: strip secret-looking values from any payload before it leaves the platform.

``scrub_secrets_from_payload`` is the recursive scrubber used by data_transfer exports, trace
serialization and domain pack exports.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Keys / patterns whose values are always treated as secrets and scrubbed
# ---------------------------------------------------------------------------

# Exact key names (case-insensitive) that must never appear with a real value
_SECRET_KEY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|_)(secret|password|passwd|token|api_key|apikey|credential|private_key|"
               r"access_key|auth_key|bearer|client_secret)s?$", re.IGNORECASE),
    re.compile(r"_secret_ref$", re.IGNORECASE),
    re.compile(r"encrypted_value", re.IGNORECASE),
]

_REDACTED = "[REDACTED]"


def _key_is_secret(key: str) -> bool:
    """Return True if the dict key name looks like it holds a sensitive value."""
    return any(p.search(key) for p in _SECRET_KEY_PATTERNS)


def scrub_secrets_from_payload(obj: Any, *, path: str = "") -> tuple[Any, list[str]]:
    """Recursively strip secret-looking values from an export payload.

    Returns a tuple (scrubbed_obj, list_of_scrubbed_paths). The second element
    is useful for generating an export_scrub audit log entry.

    Rules:
      - Dict keys matching _SECRET_KEY_PATTERNS have their values replaced with
        the sentinel string "[REDACTED]".
      - Nested dicts and lists are recursed into.
      - Scalar values (str, int, etc.) are returned unchanged unless the parent
        key matches a secret pattern.
    """
    scrubbed_paths: list[str] = []

    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else k
            if _key_is_secret(k):
                result[k] = _REDACTED
                scrubbed_paths.append(child_path)
            else:
                scrubbed_v, child_scrubbed = scrub_secrets_from_payload(v, path=child_path)
                result[k] = scrubbed_v
                scrubbed_paths.extend(child_scrubbed)
        return result, scrubbed_paths

    if isinstance(obj, list):
        result_list = []
        for i, item in enumerate(obj):
            scrubbed_item, child_scrubbed = scrub_secrets_from_payload(item, path=f"{path}[{i}]")
            result_list.append(scrubbed_item)
            scrubbed_paths.extend(child_scrubbed)
        return result_list, scrubbed_paths

    return obj, scrubbed_paths
