"""Classification policy version content: refusal codes, digests and draft validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.projection.workspace_classification_values import (
    DEFAULT_SOURCE_ADMIN,
    ClassificationValueError,
    checked_classification,
    instance_default_for,
)

from ...models import DataClassificationLevel
from .effect_rules import normalized_rules
from .level_catalog import content_registry, level_references
from .levels import (
    ERROR_LEVEL_IN_USE,
    ERROR_LEVEL_RANK_INVALID,
    LevelCatalogError,
    candidate_registry,
    catalog_of,
    level_registry,
    normalized_catalog,
)
from .policy_matrix import load_classification_policy
from .policy_rules import STATE_CONFIGURED, STATE_DEFAULT, ClassificationPolicy
from .policy_validation import normalize_policy_levels

APPROVAL_KIND = "classification_policy"
MODEL_ALIASES_RULE = "allowed_model_aliases"
MAX_NOTE_CHARS = 500

REFUSAL_NOT_FOUND = "classification_version_not_found"
REFUSAL_IN_REVIEW = "classification_draft_in_review"
REFUSAL_NO_DRAFT = "classification_draft_missing"
REFUSAL_NOT_IN_REVIEW = "classification_version_not_in_review"
REFUSAL_NO_CHANGES = "classification_draft_unchanged"
REFUSAL_TESTS_FAILED = "classification_draft_tests_failed"
REFUSAL_SELF_APPROVAL = "classification_self_approval_not_allowed"
REFUSAL_APPROVER_NOT_ADMIN = "classification_approver_not_admin"
REFUSAL_REVIEW_DECIDED = "classification_review_already_decided"
REFUSAL_DEFAULT_LEVEL = "classification_default_level_unknown"

AUDIT_DRAFT_SAVED = "admin.data_classification.draft_saved"
AUDIT_DRAFT_DISCARDED = "admin.data_classification.draft_discarded"
AUDIT_SUBMITTED = "admin.data_classification.submitted"
AUDIT_REJECTED = "admin.data_classification.rejected"
AUDIT_PUBLISHED = "admin.data_classification.published"


class ClassificationVersionError(Exception):
    def __init__(self, code: str, status: int = 409, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.details = details


# --- content ------------------------------------------------------------------------------------------------------


def content_digest(content: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def content_policy(content: Mapping[str, Any]) -> ClassificationPolicy:
    overrides = content.get("overrides") or {}
    return ClassificationPolicy(state=STATE_CONFIGURED if overrides else STATE_DEFAULT, overrides=overrides)


def _model_lists(overrides: Mapping[str, Any]) -> dict[str, Any]:
    return {level: rules[MODEL_ALIASES_RULE] for level, rules in overrides.items()
            if isinstance(rules, Mapping) and MODEL_ALIASES_RULE in rules}


def _without_model_list(item: Any) -> Any:
    if not isinstance(item, Mapping) or not isinstance(item.get("rules"), Mapping):
        return item
    return {**item, "rules": {key: value for key, value in item["rules"].items() if key != MODEL_ALIASES_RULE}}


async def normalized_content(db: AsyncSession, *, levels: Any, default_level: Any, base: Mapping[str, Any],
                             level_catalog: Any = None, effect_rules: Any = None) -> dict[str, Any]:
    base_registry = content_registry(base)
    registry = base_registry if level_catalog is None else normalized_catalog(level_catalog, base=base_registry)
    await _check_catalog(db, registry, base_registry)
    with candidate_registry(registry):
        if isinstance(levels, list):
            levels = [_without_model_list(item) for item in levels]
        overrides = normalize_policy_levels(levels)
        for level, aliases in _model_lists(base.get("overrides") or {}).items():
            if level in registry:
                overrides.setdefault(level, {})[MODEL_ALIASES_RULE] = aliases
        try:
            default = checked_classification(default_level)
        except ClassificationValueError:
            raise ClassificationVersionError(REFUSAL_DEFAULT_LEVEL, 422) from None
        rules = normalized_rules(base.get("effect_rules") if effect_rules is None else effect_rules)
    return {"overrides": overrides, "default_level": default, "level_catalog": catalog_of(registry),
            "effect_rules": [rule.to_dict() for rule in rules]}


async def _check_catalog(db: AsyncSession, registry: Any, base_registry: Any) -> None:
    retired = {row.rank: row.key for row in (await db.execute(
        select(DataClassificationLevel).where(DataClassificationLevel.retired_at.is_not(None)))).scalars()}
    for level in registry.levels:
        if base_registry.get(level.key) is None and retired.get(level.rank) not in (None, level.key):
            raise LevelCatalogError(ERROR_LEVEL_RANK_INVALID, f"level_catalog.{level.key}.rank")
    for level in base_registry.levels:
        if level.key not in registry:
            references = await level_references(db, level.key)
            if references:
                raise LevelCatalogError(ERROR_LEVEL_IN_USE, f"level_catalog.{level.key}", references=references)


# A version carries only the default an admin stored: the environment's or the platform's preset is not part of the
# policy, so publishing a version that leaves it out never switches it off.
async def stored_default_level(db: AsyncSession) -> str | None:
    default, _state, source = await instance_default_for(db)
    return default if source == DEFAULT_SOURCE_ADMIN else None


async def live_content(db: AsyncSession) -> dict[str, Any]:
    policy = await load_classification_policy(db)
    default = await stored_default_level(db)
    return {"overrides": {level: dict(rules) for level, rules in policy.overrides.items()}, "default_level": default,
            "level_catalog": catalog_of(level_registry())}
