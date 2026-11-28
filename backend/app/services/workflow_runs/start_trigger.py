"""What starts a phased workflow, as its definition says it (flow rules belong in the workflow definition, never in a
list of keys in the code)."""

from __future__ import annotations

from typing import Any

STARTED_BY_WORK_ITEM, STARTED_BY_PULL_REQUEST = "work_item", "pull_request"
STARTED_BY = (STARTED_BY_WORK_ITEM, STARTED_BY_PULL_REQUEST)


def _start_config(definition: dict[str, Any]) -> dict[str, Any]:
    for node in definition.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "start":
            return dict(node.get("config") or {}) if isinstance(node.get("config"), dict) else {}
    return {}


def started_by(definition: dict[str, Any]) -> str:
    value = str(_start_config(definition).get("started_by") or STARTED_BY_WORK_ITEM)
    return value if value in STARTED_BY else STARTED_BY_WORK_ITEM


def started_by_errors(definition: dict[str, Any]) -> list[dict[str, str]]:
    value = _start_config(definition).get("started_by")
    if value is None or value in STARTED_BY:
        return []
    return [{"code": "start_trigger_invalid", "node_id": "start",
             "message": f"The Start box's started_by is one of {', '.join(STARTED_BY)} (not {value!r})."}]


__all__ = ["STARTED_BY", "STARTED_BY_PULL_REQUEST", "STARTED_BY_WORK_ITEM", "started_by", "started_by_errors"]
