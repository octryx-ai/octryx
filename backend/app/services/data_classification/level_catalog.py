"""The level catalog of a classification version: its registry, what uses a level, publishing."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DataClassificationLevel, PolicySetVersion, PolicyTestCase, Project
from ...models.runtime.governed_revision import REVISION_STATE_PUBLISHED
from ...time_utils import utc_now
from .candidate import candidate_policy
from .levels import (
    LevelDef,
    LevelRegistry,
    candidate_registry,
    catalog_of,
    level_registry,
    set_level_registry,
)


def content_registry(content: Mapping[str, Any]) -> LevelRegistry:
    catalog = content.get("level_catalog")
    if not isinstance(catalog, list) or not catalog:
        return level_registry()
    return LevelRegistry([LevelDef(**{key: item[key] for key in LevelDef.__slots__}) for item in catalog])


@contextmanager
def content_scope(content: Mapping[str, Any]) -> Iterator[None]:
    from app.services.data_classification.policy_version_content import content_policy

    from .effect_rules import candidate_rules, rules_from_content

    with candidate_registry(content_registry(content)):
        with candidate_policy(content_policy(content)), candidate_rules(rules_from_content(content)):
            yield


async def level_references(db: AsyncSession, key: str) -> list[dict[str, str]]:
    from app.services.knowledge.projection.workspace_classification_values import instance_default_for

    from ..model_gateway.data_policy.classification import DATA_POLICY_CONFIG_KEY, declared_classification
    from ..model_gateway.data_policy.effects import gateway_aliases

    references: list[dict[str, str]] = []
    for project_id, name, config in (await db.execute(select(Project.id, Project.name, Project.config))).all():
        section = config.get(DATA_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
        if declared_classification(section) == key:
            references.append({"kind": "workspace", "id": str(project_id), "name": str(name)})
    default, _state, _source = await instance_default_for(db)
    if default == key:
        references.append({"kind": "default_level", "id": key, "name": "Level for new Workspaces"})
    for alias, data_policy_class in await gateway_aliases(db):
        if data_policy_class == key:
            references.append({"kind": "model", "id": alias, "name": alias})
    literal = json.dumps(key)
    stmt = select(PolicySetVersion).where(PolicySetVersion.state == REVISION_STATE_PUBLISHED)
    for row in (await db.execute(stmt)).scalars():
        if literal in str(row.policies_text or ""):
            references.append({"kind": "custom_policy", "id": str(row.version),
                               "name": f"Policy set version {row.version}"})
    for case in (await db.execute(select(PolicyTestCase))).scalars():
        if literal in json.dumps(case.request, sort_keys=True):
            references.append({"kind": "test_case", "id": str(case.id), "name": str(case.name)})
    return references


async def publish_catalog(db: AsyncSession, registry: LevelRegistry, *, actor_id: str) -> None:
    now = utc_now()
    rows = {row.key: row for row in (await db.execute(select(DataClassificationLevel))).scalars()}
    for level in registry.levels:
        row = rows.get(level.key)
        if row is None:
            row = DataClassificationLevel(key=level.key, rank=level.rank, builtin=level.builtin, created_by=actor_id,
                                          created_at=now)
            db.add(row)
        row.label, row.color, row.description = level.label, level.color, level.description
        row.models_allowed, row.retired_at, row.updated_at = level.models_allowed, None, now
    for key, row in rows.items():
        if key not in registry and not row.builtin and row.retired_at is None:
            row.retired_at, row.updated_at = now, now
    await db.flush()
    set_level_registry(registry)


def base_catalog() -> list[dict[str, Any]]:
    return catalog_of(level_registry())


__all__ = ["base_catalog", "content_registry", "content_scope", "level_references", "publish_catalog"]
