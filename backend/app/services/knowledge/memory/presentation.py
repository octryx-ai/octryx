"""How a memory item is shown: never as a source.

A recall entry has ``kind: "memory"`` and ``not_source_evidence: true``, carries no ``source_url`` and
no ``cite_as``, and says how to present it: "from session of <date> (confirmed|unconfirmed)", with the
session as its provenance link. Knowledge evidence reads "Source: …" with its link; the two lobes are
never rendered the same way.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ....models.project.knowledge_memory import KnowledgeMemoryItem, MemoryScope, MemoryState
from .visibility import is_expired

MEMORY_KIND = "memory"
# The recall notice is catalog data: ``knowledge.memory.notice``.


def session_link(session_id: str | None) -> str | None:
    return f"/chat?session_id={session_id}" if session_id else None


def present_as(row: KnowledgeMemoryItem) -> str:
    confirmed = "confirmed" if row.state == MemoryState.CONFIRMED.value else "unconfirmed"
    day = row.created_at.date().isoformat() if row.created_at else "an unknown date"
    origin = f"from session of {day}" if row.session_id else f"recorded on {day}"
    return f"{origin} ({confirmed})"


def _scope_label(row: KnowledgeMemoryItem) -> str:
    return "personal" if row.scope == MemoryScope.USER.value else "workspace"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def recall_entry(row: KnowledgeMemoryItem, *, recorded_by: str | None) -> dict[str, Any]:
    """One recalled memory for the model."""
    return {
        "memory_id": row.id,
        "kind": MEMORY_KIND,
        "not_source_evidence": True,
        "scope": _scope_label(row),
        "class": row.item_class,
        "author_class": row.author_class,
        "state": row.state,
        "product": row.product,
        "text": row.text,
        "recorded_by": recorded_by,
        "present_as": present_as(row),
        "provenance": {
            "session_id": row.session_id,
            "session_link": session_link(row.session_id),
            "turn_ref": row.turn_ref,
            "recorded_at": _iso(row.created_at),
        },
    }


def control_entry(
    row: KnowledgeMemoryItem, *, now: datetime, may_change: bool, recorded_by: str | None
) -> dict[str, Any]:
    """One memory item for the user-control API; a forgotten item is a tombstone without text."""
    state = (
        MemoryState.EXPIRED.value
        if row.state in (MemoryState.OBSERVED, MemoryState.CONFIRMED) and is_expired(row, now)
        else row.state
    )
    return {
        "id": row.id,
        "kind": MEMORY_KIND,
        "scope": _scope_label(row),
        "class": row.item_class,
        "author_class": row.author_class,
        "state": state,
        "product": row.product,
        "text": row.text,
        "recorded_by": recorded_by,
        "present_as": present_as(row) if row.text is not None else None,
        "session_id": row.session_id,
        "session_link": session_link(row.session_id),
        "supersedes_id": row.supersedes_id,
        "created_at": _iso(row.created_at),
        "expires_at": _iso(row.expires_at),
        "state_changed_at": _iso(row.state_changed_at),
        "may_change": may_change and row.state != MemoryState.FORGOTTEN.value,
    }


__all__ = ["MEMORY_KIND", "control_entry", "present_as", "recall_entry", "session_link"]
