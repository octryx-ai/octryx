"""Typed change records: how a versioned document's facts are classified."""

from __future__ import annotations

from .extraction_profiles import extraction_profiles

# The change-record profile: its closed types are what the change reads filter by.
CHANGE_RECORDS_PROFILE = "change-records-v2"
_CHANGE_RECORDS = extraction_profiles()[CHANGE_RECORDS_PROFILE]
# The profiles extraction writes today; an episode under any other profile is stale.
CURRENT_PROFILES = frozenset(extraction_profiles())
# The relation a fact keeps when its own self-check says it states no change (never a change type).
NOT_A_CHANGE_RELATION = "DESCRIBES"

CHANGE_EDGE_TYPES = _CHANGE_RECORDS.edge_types or {}
ACTION_REQUIRED_TYPES = _CHANGE_RECORDS.action_required_types


def change_instructions(product: str, version: str) -> str:
    return _CHANGE_RECORDS.instructions(product, version) or ""


__all__ = [
    "ACTION_REQUIRED_TYPES",
    "CHANGE_EDGE_TYPES",
    "CHANGE_RECORDS_PROFILE",
    "CURRENT_PROFILES",
    "NOT_A_CHANGE_RELATION",
    "change_instructions",
]
