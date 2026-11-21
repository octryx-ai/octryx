"""Stricter-only Workspace overrides of the classification rules (Classification → Workspaces).

A Workspace has one level; ``projects.config.data_policy.overrides = {rule: value}`` may only make a rule of that
level *stricter*: a switch only in its restrictive direction, a connector family at most the level's access, a shorter
retention, ``requires_*`` only on. The effective rules are the meet of the level's rules and the overrides
(:func:`apply_overrides`), read through :func:`workspace_level_rules` at every decision point that holds a Workspace,
so an override can never widen a rule by construction. A looser value is refused on write with the reason
(:func:`checked_overrides`); a stored override that has become equal or looser (the level changed) simply has no
effect.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..model_gateway.data_policy.classification import DATA_POLICY_CONFIG_KEY
from .policy_matrix import level_rules
from .policy_rules import (
    ACCESS_NONE,
    ACCESS_READ,
    ACCESS_READ_WRITE,
    CONNECTOR_FAMILIES,
    LevelRules,
)

OVERRIDES_FIELD = "overrides"
# The value that restricts, for each switch.
STRICT_SWITCHES: dict[str, bool] = {
    "seat_allowed": False,
    "requires_governed_routing": True,
    "reranker_allowed": False,
    "remote_embeddings_allowed": False,
    "device_runs_allowed": False,
    "log_masking_required": True,
}
_ACCESS_ORDER = {ACCESS_NONE: 0, ACCESS_READ: 1, ACCESS_READ_WRITE: 2}
MAX_RETENTION_DAYS = 36_500

ERROR_OVERRIDES_INVALID = "classification_overrides_invalid"
ERROR_OVERRIDE_UNKNOWN = "classification_override_unknown"
ERROR_OVERRIDE_LOOSER = "classification_override_looser"
ERROR_LEVEL_MISSING = "classification_override_level_missing"


class OverrideError(ValueError):
    def __init__(self, code: str, path: str, reason: str = "") -> None:
        super().__init__(f"{path}: {code}")
        self.code = code
        self.path = path
        self.reason = reason


def stored_overrides(config: Any) -> dict[str, Any]:
    section = config.get(DATA_POLICY_CONFIG_KEY) if isinstance(config, Mapping) else None
    overrides = section.get(OVERRIDES_FIELD) if isinstance(section, Mapping) else None
    return dict(overrides) if isinstance(overrides, Mapping) else {}


def shape_checked(raw: Any) -> dict[str, Any]:
    """Known rules with well-typed values (no comparison with a level). Raises :class:`OverrideError`."""
    if not isinstance(raw, Mapping):
        raise OverrideError(ERROR_OVERRIDES_INVALID, OVERRIDES_FIELD)
    checked: dict[str, Any] = {}
    for key, value in raw.items():
        path = f"{OVERRIDES_FIELD}.{key}"
        if key in STRICT_SWITCHES:
            if type(value) is not bool:
                raise OverrideError(ERROR_OVERRIDES_INVALID, path)
            checked[key] = value
        elif key == "connectors":
            if not isinstance(value, Mapping) or any(family not in CONNECTOR_FAMILIES or access not in _ACCESS_ORDER
                                                     for family, access in value.items()):
                raise OverrideError(ERROR_OVERRIDES_INVALID, path)
            checked[key] = dict(value)
        elif key == "transcript_retention_days":
            if type(value) is not int or not 1 <= value <= MAX_RETENTION_DAYS:
                raise OverrideError(ERROR_OVERRIDES_INVALID, path)
            checked[key] = value
        else:
            raise OverrideError(ERROR_OVERRIDE_UNKNOWN, path)
    return checked


def checked_overrides(raw: Any, rules: LevelRules) -> dict[str, Any]:
    """Only values stricter than ``rules``; a looser one raises with the level's value as the reason."""
    overrides = shape_checked(raw)
    kept: dict[str, Any] = {}
    for key, value in overrides.items():
        path = f"{OVERRIDES_FIELD}.{key}"
        if key in STRICT_SWITCHES:
            level_value = getattr(rules, key)
            if value == level_value:
                continue
            if value != STRICT_SWITCHES[key]:
                raise OverrideError(ERROR_OVERRIDE_LOOSER, path, f"the level already sets {key} to {level_value}")
            kept[key] = value
        elif key == "connectors":
            stricter = {}
            for family, access in value.items():
                level_access = rules.connector_access(family)
                if _ACCESS_ORDER[access] > _ACCESS_ORDER[level_access]:
                    raise OverrideError(ERROR_OVERRIDE_LOOSER, f"{path}.{family}",
                                        f"the level allows only {level_access} for {family}")
                if access != level_access:
                    stricter[family] = access
            if stricter:
                kept[key] = stricter
        else:
            level_days = rules.transcript_retention_days
            if level_days is not None and value > level_days:
                raise OverrideError(ERROR_OVERRIDE_LOOSER, path, f"the level keeps transcripts {level_days} days")
            if value != level_days:
                kept[key] = value
    return kept


def apply_overrides(rules: LevelRules, overrides: Mapping[str, Any]) -> LevelRules:
    """The meet of a level's rules and a Workspace's overrides: never looser than ``rules``."""
    if not overrides:
        return rules
    values: dict[str, Any] = {}
    for key, strict in STRICT_SWITCHES.items():
        if overrides.get(key) == strict:
            values[key] = strict
    if isinstance(overrides.get("connectors"), Mapping):
        connectors = dict(rules.connectors)
        for family, access in overrides["connectors"].items():
            if access in _ACCESS_ORDER and _ACCESS_ORDER[access] < _ACCESS_ORDER[rules.connector_access(family)]:
                connectors[family] = access
        values["connectors"] = connectors
    days = overrides.get("transcript_retention_days")
    if type(days) is int and (rules.transcript_retention_days is None or days < rules.transcript_retention_days):
        values["transcript_retention_days"] = days
    return replace(rules, **values) if values else rules


async def workspace_level_rules(db: AsyncSession, config: Any, level: str) -> LevelRules:
    """The rules a Workspace at ``level`` runs under: the level's rules met with its stricter overrides."""
    return apply_overrides(await level_rules(db, level), stored_overrides(config))


async def workspace_rules_by_id(db: AsyncSession, workspace_id: str | None, level: str) -> LevelRules:
    """:func:`workspace_level_rules` for a Workspace id (its stored config row)."""
    from sqlalchemy import select

    from ...models import Project

    config = None
    if workspace_id:
        config = (await db.execute(select(Project.config).where(Project.id == workspace_id))).scalar_one_or_none()
    return await workspace_level_rules(db, config, level)


WORKSPACE_OVERRIDES_AUDIT_ACTION = "admin.data_classification.workspace_overrides_updated"


async def set_workspace_overrides(db: AsyncSession, *, project: Any, overrides: Any, actor_id: str) -> dict[str, Any]:
    """Store a Workspace's stricter overrides against its current level (governed config path + audit). Flushes.

    Raises :class:`OverrideError` for an unknown rule, a bad value or a looser one (with the level's value).
    """
    from ...models import AuditLog
    from ..admin.project.admin_project_config_service import apply_project_config_patch
    from ..model_gateway.data_policy.classification import declared_classification

    config = project.config if isinstance(project.config, Mapping) else {}
    stored = config.get(DATA_POLICY_CONFIG_KEY)
    section = dict(stored) if isinstance(stored, Mapping) else {}
    level = declared_classification(section)
    if not level:
        raise OverrideError(ERROR_LEVEL_MISSING, OVERRIDES_FIELD, "the Workspace has no level")
    before = stored_overrides(config)
    kept = checked_overrides(overrides, await level_rules(db, level))
    section[OVERRIDES_FIELD] = kept  # always sent: the config merge is one level deep, so {} clears the overrides
    await apply_project_config_patch(db, project=project, patch={DATA_POLICY_CONFIG_KEY: section},
                                     actor_user_id=actor_id)
    db.add(AuditLog(user_id=actor_id, action=WORKSPACE_OVERRIDES_AUDIT_ACTION, resource_type="workspace",
                    resource_id=project.id, details={"level": level, "before": before, "after": kept}))
    await db.flush()
    return kept


__all__ = [
    "ERROR_OVERRIDE_LOOSER",
    "WORKSPACE_OVERRIDES_AUDIT_ACTION",
    "set_workspace_overrides",
    "OVERRIDES_FIELD",
    "STRICT_SWITCHES",
    "OverrideError",
    "apply_overrides",
    "checked_overrides",
    "shape_checked",
    "stored_overrides",
    "workspace_level_rules",
    "workspace_rules_by_id",
]
