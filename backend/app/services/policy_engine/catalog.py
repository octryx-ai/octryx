"""The policy catalog: the builder's building blocks, code-owned next to the schema.

``policy_catalog.json`` lists the enforcement points, principals, resources, actions (plain language, group,
enforcement point), context fields, the condition blocks the builder can combine and the built-in templates.
It is keyed by :data:`schema.SCHEMA_VERSION`: a schema change is a catalog change (the coverage test
asserts that every action, entity type, attribute and context field of the ``.cedarschema`` is described), so
the UI never hard-codes an action.

Two block scopes are resolved here, not in the file, because they follow what the enforcement points carry:
``"all"`` (every action) and ``"classified"`` (the actions whose point knows the Workspace classification).
Whether a point carries the user (who-conditions take effect) or the classification is the point's
``carries_user`` / ``carries_classification`` flag.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .schema import ACTIONS, SCHEMA_VERSION

CATALOG_PATH = Path(__file__).with_name("policy_catalog.json")
SCOPE_ALL = "all"
SCOPE_CLASSIFIED = "classified"


class CatalogError(RuntimeError):
    """The catalog file does not match the code (a packaging or review defect)."""


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(f"policy catalog is for schema {data.get('schema_version')}, code is {SCHEMA_VERSION}")
    if {item["id"] for item in data["actions"]} != set(ACTIONS):
        raise CatalogError("policy catalog actions differ from schema.ACTIONS")
    return data


def _points() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in _raw()["enforcement_points"]}


def action_info(action_id: str) -> dict[str, Any]:
    for item in _raw()["actions"]:
        if item["id"] == action_id:
            return item
    raise KeyError(action_id)


def action_ids() -> tuple[str, ...]:
    """The actions in catalog order (the builder renders and lists them in this order)."""
    return tuple(item["id"] for item in _raw()["actions"])


def point_of(action_id: str) -> dict[str, Any]:
    return _points()[action_info(action_id)["point"]]


def carries_user(action_id: str) -> bool:
    return bool(point_of(action_id).get("carries_user"))


def carries_classification(action_id: str) -> bool:
    return bool(point_of(action_id).get("carries_classification"))


def _resolved_actions(scope: Any) -> list[str]:
    if scope == SCOPE_ALL:
        return list(action_ids())
    if scope == SCOPE_CLASSIFIED:
        return [action for action in action_ids() if carries_classification(action)]
    return [action for action in action_ids() if action in set(scope or ())]


def block_info(block_id: str) -> dict[str, Any]:
    for item in _raw()["condition_blocks"]:
        if item["id"] == block_id:
            resolved = dict(item)
            resolved["actions"] = _resolved_actions(item.get("actions"))
            return resolved
    raise KeyError(block_id)


def block_ids() -> tuple[str, ...]:
    return tuple(item["id"] for item in _raw()["condition_blocks"])


def classification_levels() -> tuple[str, ...]:
    """The level keys, least sensitive first, from the level registry (not the JSON file)."""
    from ..data_classification.levels import level_registry

    return level_registry().order


def data_policy_classes() -> tuple[str, ...]:
    """The levels a model may be cleared for, from the level registry."""
    from ..data_classification.levels import level_registry

    return level_registry().model_levels()


def connector_families() -> tuple[str, ...]:
    from app.services.data_classification.policy_rules import CONNECTOR_FAMILIES

    return CONNECTOR_FAMILIES


def client_tools() -> tuple[str, ...]:
    for item in _raw()["context"]:
        if item["name"] == "tool":
            return tuple(item["values"])
    return ()


def templates() -> list[dict[str, Any]]:
    return copy.deepcopy(_raw()["templates"])


def template_info(template_id: str) -> dict[str, Any] | None:
    return next((item for item in templates() if item["id"] == template_id), None)


def catalog_payload() -> dict[str, Any]:
    """The catalog as served (``GET …/catalog``): block action scopes resolved, connector families listed."""
    data = copy.deepcopy(_raw())
    data["condition_blocks"] = [block_info(item["id"]) for item in data["condition_blocks"]]
    data["connector_families"] = list(connector_families())
    data["classification_levels"] = list(classification_levels())
    data["data_policy_classes"] = list(data_policy_classes())
    for action in data["actions"]:
        point = _points()[action["point"]]
        action["point_label"] = point["label"]
        action["point_when"] = point["checked_when"]
        action["carries_user"] = bool(point.get("carries_user"))
        action["carries_classification"] = bool(point.get("carries_classification"))
    return data


__all__ = [
    "CATALOG_PATH",
    "CatalogError",
    "action_ids",
    "action_info",
    "block_ids",
    "block_info",
    "carries_classification",
    "carries_user",
    "catalog_payload",
    "classification_levels",
    "client_tools",
    "connector_families",
    "data_policy_classes",
    "point_of",
    "template_info",
    "templates",
]
