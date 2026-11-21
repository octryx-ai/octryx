"""Shared session helpers used across session service modules."""

from __future__ import annotations

from typing import Any


def get_session_metadata(session: Any) -> dict[str, Any]:
    metadata = session.metadata_ or {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def get_session_metadata_text(session: Any, key: str) -> str:
    return str(get_session_metadata(session).get(key) or "").strip()


def set_session_metadata_value(session: Any, key: str, value: Any) -> None:
    metadata = get_session_metadata(session)
    if value in (None, ""):
        metadata.pop(key, None)
    else:
        metadata[key] = value
    session.metadata_ = metadata
