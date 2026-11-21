"""The Instance default's vocabulary, its configured value and the ``data_policy`` reads behind
``workspace_classification_default``."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....config import get_settings
from ...model_gateway.data_policy.classification import (
    DATA_CLASSIFICATION_LEVELS,
    DATA_POLICY_CLASSIFICATION_CLEARED_FIELD,
    DATA_POLICY_CLASSIFICATION_FIELD,
    DATA_POLICY_CONFIG_KEY,
    declared_classification,
    normalized_classification,
)
from ...system_config.values import get_system_config_value

DEFAULT_AUDIT_ACTION = "knowledge.workspace.data_classification_default"
_CONFIG_AUDIT_ACTION = "admin.project_config.updated"

SOURCE_WORKSPACE = "workspace"
SOURCE_INSTANCE_DEFAULT = "instance_default"
SOURCE_UNSET = "unset"

DEFAULT_SET = "set"
DEFAULT_UNSET = "unset"
DEFAULT_INVALID = "invalid"

INSTANCE_DEFAULT_CONFIG_KEY = "knowledge.default_data_classification"
INSTANCE_DEFAULT_NONE = "none"
INSTANCE_DEFAULT_AUDIT_ACTION = "admin.data_classification.default_updated"
WORKSPACE_CLASSIFICATION_AUDIT_ACTION = "admin.data_classification.workspace_updated"
DEFAULT_SOURCE_ADMIN = "admin"
DEFAULT_SOURCE_ENV = "env"
REASON_CLASSIFICATION_UNKNOWN = "data_classification_unknown"


class ClassificationValueError(ValueError):
    """A classification outside ``DATA_CLASSIFICATION_ORDER``; ``code`` is fixed."""

    code = REASON_CLASSIFICATION_UNKNOWN


def checked_classification(value: object) -> str | None:
    """``None`` for ``None``/empty, the normalized level, or ``ClassificationValueError``."""
    if value is None:
        return None
    if type(value) is not str:
        raise ClassificationValueError(REASON_CLASSIFICATION_UNKNOWN)
    normalized = normalized_classification(value)
    if not normalized:
        return None
    if normalized not in DATA_CLASSIFICATION_LEVELS:
        raise ClassificationValueError(REASON_CLASSIFICATION_UNKNOWN)
    return normalized


def instance_default_classification() -> tuple[str | None, str]:
    """The configured default and its state: ``set``, ``unset`` or ``invalid`` (outside the vocabulary)."""
    value = normalized_classification(get_settings().knowledge_default_data_classification)
    if not value:
        return None, DEFAULT_UNSET
    if value not in DATA_CLASSIFICATION_LEVELS:
        return None, DEFAULT_INVALID
    return value, DEFAULT_SET


# The admin-stored default as last read (``None`` = not read yet); synchronous decision points read it through
# :func:`known_instance_default`. Refreshed with the policy runtime and on every read or write of the default.
_known_admin_default: list[tuple[str | None]] = []


def known_instance_default() -> str | None:
    """The Instance default for a synchronous decision point: the admin value as last read, else the env value."""
    if _known_admin_default:
        return _known_admin_default[0][0]
    return instance_default_classification()[0]


async def instance_default_for(db: AsyncSession) -> tuple[str | None, str, str]:
    """``(default, state, source)``: the admin-stored value wins over the env bootstrap value."""
    result = await _instance_default_for(db)
    if result[2] == DEFAULT_SOURCE_ADMIN:
        _known_admin_default[:] = [(result[0],)]
    else:
        _known_admin_default.clear()
    return result


async def _instance_default_for(db: AsyncSession) -> tuple[str | None, str, str]:
    stored = await get_system_config_value(db, INSTANCE_DEFAULT_CONFIG_KEY)
    if stored is not None:
        value = normalized_classification(stored)
        if value == INSTANCE_DEFAULT_NONE:
            return None, DEFAULT_UNSET, DEFAULT_SOURCE_ADMIN
        if value in DATA_CLASSIFICATION_LEVELS:
            return value, DEFAULT_SET, DEFAULT_SOURCE_ADMIN
        return None, DEFAULT_INVALID, DEFAULT_SOURCE_ADMIN
    value, state = instance_default_classification()
    return value, state, DEFAULT_SOURCE_ENV if state != DEFAULT_UNSET else SOURCE_UNSET


def _section(config: object) -> dict:
    """The stored ``data_policy`` block without its classification fields, so a level write keeps the rest
    (the stricter Workspace overrides)."""
    section = config.get(DATA_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    if not isinstance(section, dict):
        return {}
    return {key: value for key, value in section.items()
            if key not in {DATA_POLICY_CLASSIFICATION_FIELD, DATA_POLICY_CLASSIFICATION_CLEARED_FIELD}}


def _declared(config: object) -> str:
    return declared_classification(config.get(DATA_POLICY_CONFIG_KEY) if isinstance(config, dict) else None)


def _may_default(config: object) -> bool:
    """Only a Workspace with no classification of its own: none set, none cleared, nothing unreadable."""
    section = config.get(DATA_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    if section is None:
        return True
    if not isinstance(section, dict):
        return False  # a data_policy the gate cannot read stays as it is
    return not _declared(config) and not section.get(DATA_POLICY_CLASSIFICATION_CLEARED_FIELD)
