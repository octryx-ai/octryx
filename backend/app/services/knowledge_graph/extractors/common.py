"""Shared helpers for graph extractors."""

from __future__ import annotations

import re

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    return _SLUG.sub("-", str(value or "").strip().lower()).strip("-") or "unknown"
