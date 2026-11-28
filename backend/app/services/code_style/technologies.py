"""The technologies a specification decision can name: a built-in catalog under the installation's, the Workspace's and
the repository's own entries."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .schema_values import CodeStyleError

KINDS = ("library", "platform_api")
MAX_ENTRIES = 300
MAX_ITEMS = 40
CATALOG = Path(__file__).with_name("technologies.json")


@lru_cache(maxsize=1)
def built_in() -> dict[str, dict[str, Any]]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _strings(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS or any(
            not isinstance(item, str) or not item.strip() or len(item) > 120 for item in value):
        raise CodeStyleError("invalid_technology", path)
    return [item.strip() for item in value]


def normalize(value: Any, path: str = "code_style.technologies") -> dict[str, Any]:
    if not isinstance(value, dict) or len(value) > MAX_ENTRIES:
        raise CodeStyleError("invalid_technologies", path)
    out: dict[str, Any] = {}
    for key, entry in value.items():
        where = f"{path}.{key}"
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,60}", key):
            raise CodeStyleError("invalid_technology", where)
        if entry is None:
            out[key] = None
            continue
        if not isinstance(entry, dict) or set(entry) - {"kind", "words", "packages", "uses"} or \
                entry.get("kind", "library") not in KINDS:
            raise CodeStyleError("invalid_technology", where)
        uses = entry.get("uses")
        if not isinstance(uses, str) or not uses or len(uses) > 600:
            raise CodeStyleError("invalid_technology", f"{where}.uses")
        try:
            re.compile(uses)
        except re.error as error:
            raise CodeStyleError("invalid_pattern", f"{where}.uses") from error
        words = _strings(entry.get("words"), f"{where}.words")
        if not words:
            raise CodeStyleError("invalid_technology", f"{where}.words")
        out[key] = {"kind": entry.get("kind", "library"), "words": words,
                    "packages": _strings(entry.get("packages", []), f"{where}.packages"), "uses": uses}
    return out


def catalog(levels: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    merged = dict(built_in())
    for level in ("installation", "workspace", "repository"):
        for key, entry in dict(dict(levels or {}).get(level, {}).get("technologies") or {}).items():
            if entry is None:
                merged.pop(key, None)
            else:
                merged[key] = entry
    return merged


__all__ = ["KINDS", "built_in", "catalog", "normalize"]
