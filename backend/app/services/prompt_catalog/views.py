"""Read views of the prompt catalog for the admin API: list, detail and diff."""

from __future__ import annotations

import difflib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.governed_revision import REVISION_STATE_PUBLISHED
from ...models.runtime.prompt_template import (
    PROMPT_SCOPE_GLOBAL,
    PROMPT_SCOPE_WORKSPACE,
    PromptTemplate,
    PromptTemplateVersion,
)
from .contract import PromptKeySpec, body_placeholders, prompt_digest
from .lifecycle import PromptCatalogRefusal, load_version, versions_of
from .registry import prompt_key_registry, prompt_key_spec


def serialize_spec(spec: PromptKeySpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "area": spec.area,
        "title": spec.title,
        "description": spec.description,
        "risk": spec.risk,
        "placeholders": sorted(spec.placeholders),
        "literal": spec.literal,
        "group": spec.group,
        "group_order": spec.group_order,
        "placeholder_descriptions": dict(spec.placeholder_descriptions),
    }


def serialize_version(version: PromptTemplateVersion, *, include_body: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": version.id,
        "version": version.version,
        "state": version.state,
        "source": version.source,
        "digest": version.digest,
        "change_note": version.change_note,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "approval_id": version.approval_id,
        "published_by": version.published_by,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "retired_at": version.retired_at.isoformat() if version.retired_at else None,
    }
    if include_body:
        payload["body"] = version.body
        payload["placeholders_used"] = list(body_placeholders(version.body))
    return payload


def serialize_template(template: PromptTemplate, versions: list[PromptTemplateVersion]) -> dict[str, Any]:
    return {
        "id": template.id,
        "key": template.key,
        "scope_type": template.scope_type,
        "scope_id": template.scope_id,
        "scope_key": template.scope_key,
        "versions": [serialize_version(item) for item in versions],
    }


#: Areas with hundreds of keys (one per tool and parameter): listed only when asked for by name.
COLLAPSED_AREAS = frozenset({"tool", "mcp"})


def catalog_areas() -> dict[str, int]:
    counts: dict[str, int] = {}
    for spec in prompt_key_registry().values():
        counts[spec.area] = counts.get(spec.area, 0) + 1
    return dict(sorted(counts.items()))


async def list_catalog(db: AsyncSession, *, area: str | None = None) -> list[dict[str, Any]]:
    specs = [
        spec
        for spec in prompt_key_registry().values()
        if (spec.area == area if area else spec.area not in COLLAPSED_AREAS)
    ]
    keys = {spec.key for spec in specs}
    templates = [
        item for item in (await db.execute(select(PromptTemplate))).scalars().all() if item.key in keys
    ]
    versions = await versions_of(db, [item.id for item in templates])
    by_template: dict[str, list[PromptTemplateVersion]] = {}
    for version in versions:
        by_template.setdefault(version.template_id, []).append(version)
    by_key: dict[str, list[PromptTemplate]] = {}
    for template in templates:
        by_key.setdefault(template.key, []).append(template)
    items: list[dict[str, Any]] = []
    for spec in specs:
        rows = by_key.get(spec.key, [])
        global_row = next((item for item in rows if item.scope_type == PROMPT_SCOPE_GLOBAL), None)
        global_versions = by_template.get(global_row.id, []) if global_row else []
        published = next((item for item in global_versions if item.state == REVISION_STATE_PUBLISHED), None)
        open_versions = [item for item in global_versions if item.state in {"draft", "in_review"}]
        items.append(
            {
                **serialize_spec(spec),
                "published": serialize_version(published, include_body=False) if published else None,
                "seed_digest": prompt_digest(spec.seed),
                "open_versions": len(open_versions),
                "override_count": sum(1 for item in rows if item.scope_type != PROMPT_SCOPE_GLOBAL),
            }
        )
    return items


async def catalog_detail(db: AsyncSession, key: str, *, reader_id: str | None = None) -> dict[str, Any]:
    from .scope_rights import may_write

    spec = _spec_or_refusal(key)
    templates = list((await db.execute(select(PromptTemplate).where(PromptTemplate.key == key))).scalars().all())
    if reader_id is not None:
        templates = [item for item in templates if item.scope_type == "global"
                     or await may_write(db, reader_id, item.scope_type, item.scope_id)]
    versions = await versions_of(db, [item.id for item in templates])
    return {
        **serialize_spec(spec),
        "seed": spec.seed,
        "seed_digest": prompt_digest(spec.seed),
        "templates": [
            serialize_template(item, [v for v in versions if v.template_id == item.id])
            for item in sorted(templates, key=_scope_order)
        ],
    }


async def version_diff(db: AsyncSession, version_id: str) -> dict[str, Any]:
    template, version = await load_version(db, version_id)
    baseline, baseline_ref = await _baseline(db, template)
    lines = list(
        difflib.unified_diff(
            baseline.splitlines(keepends=True),
            version.body.splitlines(keepends=True),
            fromfile=baseline_ref,
            tofile=f"{template.key}@{version.version}",
        )
    )
    return {
        "version_id": version.id,
        "baseline": baseline_ref,
        "identical": baseline == version.body,
        "diff": "".join(lines),
    }


async def _baseline(db: AsyncSession, template: PromptTemplate) -> tuple[str, str]:
    spec = prompt_key_spec(template.key)
    for scope_type, scope_id in _lower_scopes(template):
        row = (
            await db.execute(
                select(PromptTemplateVersion)
                .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.template_id)
                .where(
                    PromptTemplate.key == template.key,
                    PromptTemplate.scope_type == scope_type,
                    PromptTemplate.scope_id.is_(None) if scope_id is None else PromptTemplate.scope_id == scope_id,
                    PromptTemplateVersion.state == REVISION_STATE_PUBLISHED,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row.body, f"{template.key}@{row.version} ({scope_type})"
    return spec.seed, f"{template.key}@seed"


def _lower_scopes(template: PromptTemplate) -> list[tuple[str, str | None]]:
    scopes: list[tuple[str, str | None]] = [(template.scope_type, template.scope_id)]
    if template.scope_type == PROMPT_SCOPE_WORKSPACE:
        scopes.append((PROMPT_SCOPE_GLOBAL, None))
    return scopes


def _scope_order(template: PromptTemplate) -> tuple[int, str]:
    order = {PROMPT_SCOPE_GLOBAL: 0, PROMPT_SCOPE_WORKSPACE: 1}
    return order.get(template.scope_type, 9), template.scope_key


def _spec_or_refusal(key: str) -> PromptKeySpec:
    spec = prompt_key_registry().get(key)
    if spec is None:
        raise PromptCatalogRefusal("prompt_key_not_found", 404, key=key)
    return spec


__all__ = ["COLLAPSED_AREAS", "catalog_areas", "catalog_detail", "list_catalog", "serialize_version", "version_diff"]
