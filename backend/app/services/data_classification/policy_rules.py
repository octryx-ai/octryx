"""The policy matrix vocabulary: rule names, error codes, the per-level rules and the policy value."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any

from ...models.security.data_classification import CLASSIFICATION_CONFIDENTIAL
from ..model_gateway.data_policy.classification import DATA_CLASSIFICATION_ORDER, classification_rank

POLICY_MATRIX_CONFIG_KEY = "data_classification.policy_matrix"

CONNECTOR_FAMILIES: tuple[str, ...] = ("servicenow", "jira", "confluence", "kubernetes", "aws", "bitbucket")
ACCESS_NONE = "none"
ACCESS_READ = "read"
ACCESS_READ_WRITE = "read_write"
CONNECTOR_ACCESS: tuple[str, ...] = (ACCESS_NONE, ACCESS_READ, ACCESS_READ_WRITE)

RULE_KEYS: tuple[str, ...] = (
    "seat_allowed",
    "allowed_model_aliases",
    "reranker_allowed",
    "remote_embeddings_allowed",
    "connectors",
    "requires_governed_routing",
    "log_masking_required",
    "transcript_retention_days",
    "device_runs_allowed",
)
_BOOL_RULES = frozenset(
    {"seat_allowed", "reranker_allowed", "remote_embeddings_allowed", "requires_governed_routing",
     "log_masking_required", "device_runs_allowed"}
)

STATE_DEFAULT = "default"
STATE_CONFIGURED = "configured"
STATE_INVALID = "invalid"

ERROR_LEVELS_INVALID = "classification_policy_levels_invalid"
ERROR_LEVEL_UNKNOWN = "classification_policy_level_unknown"
ERROR_LEVEL_DUPLICATE = "classification_policy_level_duplicate"
ERROR_RULES_INVALID = "classification_policy_rules_invalid"
ERROR_RULE_UNKNOWN = "classification_policy_rule_unknown"
ERROR_RULE_INVALID = "classification_policy_rule_invalid"
ERROR_CONNECTOR_FAMILY_UNKNOWN = "classification_policy_connector_family_unknown"
ERROR_CONNECTOR_ACCESS_INVALID = "classification_policy_connector_access_invalid"

MAX_ALIASES = 100
MAX_RETENTION_DAYS = 36_500
_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
# Rules the matrix shows but does not store: derived from the Model catalog clearance.
DERIVED_RULE_KEYS: frozenset[str] = frozenset({"allowed_model_aliases"})


class ClassificationPolicyError(ValueError):
    def __init__(self, code: str, path: str) -> None:
        super().__init__(f"{path}: {code}")
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class LevelRules:
    seat_allowed: bool
    allowed_model_aliases: tuple[str, ...] | None = None
    reranker_allowed: bool = True
    remote_embeddings_allowed: bool = True
    connectors: Mapping[str, str] = field(
        default_factory=lambda: dict.fromkeys(CONNECTOR_FAMILIES, ACCESS_READ_WRITE)
    )
    requires_governed_routing: bool = False
    log_masking_required: bool = False
    transcript_retention_days: int | None = None
    device_runs_allowed: bool = True

    @property
    def seat_in_policy(self) -> bool:
        return self.seat_allowed and not self.requires_governed_routing

    def connector_access(self, family: str) -> str:
        return str(self.connectors.get(family, ACCESS_READ_WRITE))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_model_aliases"] = (
            list(self.allowed_model_aliases) if self.allowed_model_aliases is not None else None
        )
        payload["connectors"] = {family: self.connector_access(family) for family in CONNECTOR_FAMILIES}
        return payload


def default_rules(level: str) -> LevelRules:
    rank = classification_rank(level)
    return LevelRules(seat_allowed=rank is not None and rank < classification_rank(CLASSIFICATION_CONFIDENTIAL))


# Fail-closed rules for an unreadable stored matrix.
LOCKED_RULES = LevelRules(
    seat_allowed=False,
    allowed_model_aliases=(),
    reranker_allowed=False,
    remote_embeddings_allowed=False,
    connectors=dict.fromkeys(CONNECTOR_FAMILIES, ACCESS_NONE),
    requires_governed_routing=True,
    device_runs_allowed=False,
)


@dataclass(frozen=True, slots=True)
class ClassificationPolicy:
    state: str
    overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    updated_at: datetime | None = None
    updated_by: str | None = None
    # ``{level: aliases}`` from the Model catalog clearance (``load_classification_policy`` fills every level);
    # a level absent here (or ``None``: no database read) does not narrow.
    derived_model_aliases: Mapping[str, tuple[str, ...]] | None = None

    def rules_for(self, level: str) -> LevelRules:
        if self.state == STATE_INVALID:
            return LOCKED_RULES
        rules = _apply(default_rules(level), self.overrides.get(level) or {})
        if self.derived_model_aliases is None or level not in self.derived_model_aliases:
            return rules
        return replace(rules, allowed_model_aliases=tuple(self.derived_model_aliases[level]))

    def levels(self) -> dict[str, LevelRules]:
        return {level: self.rules_for(level) for level in DATA_CLASSIFICATION_ORDER}

    def model_allowlists(self) -> dict[str, frozenset[str]]:
        return {
            level: frozenset(rules.allowed_model_aliases)
            for level, rules in self.levels().items()
            if rules.allowed_model_aliases is not None
        }


DEFAULT_POLICY = ClassificationPolicy(state=STATE_DEFAULT)


def _apply(base: LevelRules, override: Mapping[str, Any]) -> LevelRules:
    values = dict(override)
    if "connectors" in values:
        values["connectors"] = {**base.connectors, **values["connectors"]}
    if values.get("allowed_model_aliases") is not None:
        values["allowed_model_aliases"] = tuple(values["allowed_model_aliases"])
    return replace(base, **values)
