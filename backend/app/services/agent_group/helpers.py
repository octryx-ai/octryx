"""Shared agent-group helpers."""

from __future__ import annotations

import re


def slugify_group_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    normalized = normalized.strip("-")
    return normalized or "group"
