"""Where the workflow designer draws each node of a workflow that runs in phases."""

from __future__ import annotations

import math
from typing import Any

LAYOUT_KEY = "layout"
POSITIONS_KEY = "positions"
GROUPS_KEY = "groups"
DIRECTION_KEY = "direction"
DIRECTIONS = frozenset({"tb", "lr"})
_LABEL_LIMIT = 120
_GROUP_LIMIT = 200
# A canvas coordinate beyond this is a broken client, not a layout; the node falls back to the auto-layout.
_LIMIT = 1_000_000.0


def _coordinate(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or abs(number) > _LIMIT:
        return None
    return round(number, 1)


def clean_positions(raw: Any, node_ids: set[str] | frozenset[str]) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict):
        return {}
    positions: dict[str, dict[str, float]] = {}
    for node_id in sorted(str(key) for key in raw if str(key) in node_ids):
        point = raw.get(node_id)
        if not isinstance(point, dict):
            continue
        x, y = _coordinate(point.get("x")), _coordinate(point.get("y"))
        if x is not None and y is not None:
            positions[node_id] = {"x": x, "y": y}
    return positions


def layout_positions(definition: dict[str, Any], node_ids: set[str] | frozenset[str]) -> dict[str, dict[str, float]]:
    block = definition.get(LAYOUT_KEY)
    return clean_positions(block.get(POSITIONS_KEY) if isinstance(block, dict) else None, node_ids)


def clean_groups(raw: Any, node_ids: set[str] | frozenset[str]) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    groups: list[dict[str, Any]] = []
    taken: set[str] = set()
    ids: set[str] = set()
    for item in raw[:_GROUP_LIMIT]:
        if not isinstance(item, dict):
            continue
        group_id = str(item.get("id") or "").strip()
        if not group_id or group_id in ids:
            continue
        label = item.get("label")
        members: list[str] = []
        for member in item.get("members") if isinstance(item.get("members"), list) else []:
            if isinstance(member, str) and member in node_ids and member not in taken:
                members.append(member)
                taken.add(member)
        if not members:
            continue
        ids.add(group_id)
        groups.append({"id": group_id, "label": label.strip()[:_LABEL_LIMIT] if isinstance(label, str) else "",
                       "members": members})
    return groups


def layout_groups(definition: dict[str, Any], node_ids: set[str] | frozenset[str]) -> list[dict[str, Any]] | None:
    block = definition.get(LAYOUT_KEY)
    return clean_groups(block.get(GROUPS_KEY) if isinstance(block, dict) else None, node_ids)


def with_layout(definition: dict[str, Any], positions: dict[str, dict[str, float]],
                groups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    edited = dict(definition)
    block = dict(edited.get(LAYOUT_KEY) or {}) if isinstance(edited.get(LAYOUT_KEY), dict) else {}
    block.pop(POSITIONS_KEY, None)
    if positions:
        block[POSITIONS_KEY] = positions
    if groups is not None:
        block[GROUPS_KEY] = groups
    if block:
        edited[LAYOUT_KEY] = block
    else:
        edited.pop(LAYOUT_KEY, None)
    return edited


def with_clean_layout(definition: dict[str, Any], node_ids: set[str] | frozenset[str]) -> dict[str, Any]:
    block = definition.get(LAYOUT_KEY)
    if not isinstance(block, dict):
        edited = dict(definition)
        edited.pop(LAYOUT_KEY, None)
        return edited
    groups = layout_groups(definition, node_ids)
    cleaned = {key: value for key, value in definition.items() if key != LAYOUT_KEY}
    if block.get(DIRECTION_KEY) in DIRECTIONS:
        cleaned[LAYOUT_KEY] = {DIRECTION_KEY: block[DIRECTION_KEY]}
    return with_layout(cleaned, layout_positions(definition, node_ids), groups)


def layout_direction(definition: dict[str, Any]) -> str | None:
    block = definition.get(LAYOUT_KEY)
    direction = block.get(DIRECTION_KEY) if isinstance(block, dict) else None
    return direction if direction in DIRECTIONS else None


__all__ = [
    "DIRECTION_KEY", "GROUPS_KEY", "LAYOUT_KEY", "POSITIONS_KEY", "clean_groups", "clean_positions", "layout_direction",
    "layout_groups", "layout_positions", "with_clean_layout", "with_layout",
]
