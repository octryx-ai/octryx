"""Shared helpers and validation constants for Engineering Knowledge admin services."""

from __future__ import annotations

from typing import Any

_VALID_VERSION_STATUSES = {"draft", "pending_review", "published", "rejected", "stale", "revoked", "archived"}
_VALID_ASSIGNMENT_STATUSES = {"active", "inactive"}
_VALID_SCOPE_TYPES = {"global", "workspace", "project", "repository"}
_GRAPH_NODE_STATUSES = {"active", "draft", "rejected", "retracted", "expired", "stale"}
_GRAPH_TRUST_LEVELS = {"bronze", "silver", "gold", "official", "verified", "untrusted"}
_GRAPH_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted", "secret"}


def _optional_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _pagination(limit: int | None, offset: int | None, *, max_limit: int = 200) -> tuple[int, int]:
    safe_limit = max(1, min(int(limit or 50), max_limit))
    safe_offset = max(0, int(offset or 0))
    return safe_limit, safe_offset
