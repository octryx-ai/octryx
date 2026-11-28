"""Content digest of a registry document (``sha256:<hex>`` over canonical JSON)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

DIGEST_PREFIX = "sha256:"


def _normalize_numbers(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_numbers(item) for item in value]
    return value


def canonical_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(
        _normalize_numbers(document), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def content_digest(document: dict[str, Any]) -> str:
    return DIGEST_PREFIX + hashlib.sha256(canonical_bytes(document)).hexdigest()


__all__ = ["DIGEST_PREFIX", "canonical_bytes", "content_digest"]
