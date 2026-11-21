"""Prompt configuration revision ledger and rollback helpers (system prompt variant routing).

The system prompt template texts are prompt catalog data (``services/prompt_catalog``); this ledger records the
variant routing only: the global routing key and each Workspace's ``variant_routing`` entries.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.core.prompts.prompt_templates import (
    PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY,
    normalize_system_prompt_variant_routing,
)
from app.models import Project, PromptConfigRevision, SystemConfig
from app.services.system_config.constants import AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY

PROMPT_SCOPE_GLOBAL = "global"
PROMPT_SCOPE_PROJECT = "project"
PROMPT_CHANGE_SOURCE_SYSTEM_CONFIG = "system_config"
PROMPT_CHANGE_SOURCE_PROJECT_CONFIG = "project_config"
PROMPT_CHANGE_SOURCE_ROLLBACK = "rollback"

_DELETED_VALUE_CHECKSUM_INPUT = "\x00prompt-config-deleted\x00"


@dataclass(frozen=True)
class PromptConfigEntry:
    config_key: str
    variant_key: str | None
    value: str | None


async def record_system_prompt_revision_if_applicable(
    db: AsyncSession,
    *,
    config_key: str,
    value: str | None,
    created_by: str | None = None,
    change_source: str = PROMPT_CHANGE_SOURCE_SYSTEM_CONFIG,
    revision_metadata: Mapping[str, object] | None = None,
) -> PromptConfigRevision | None:
    """Record a global system prompt config revision when the key is prompt-related."""

    entry = _classify_system_prompt_config_key(config_key)
    if entry is None:
        return None
    return await record_prompt_config_revision(
        db,
        scope_type=PROMPT_SCOPE_GLOBAL,
        scope_id=None,
        config_key=config_key,
        variant_key=entry.variant_key,
        value=value,
        created_by=created_by,
        change_source=change_source,
        revision_metadata=revision_metadata,
    )


async def record_project_prompt_revisions(
    db: AsyncSession,
    *,
    project_id: str,
    before_config: Mapping[str, object] | None,
    after_config: Mapping[str, object] | None,
    created_by: str | None = None,
    change_source: str = PROMPT_CHANGE_SOURCE_PROJECT_CONFIG,
) -> list[PromptConfigRevision]:
    """Record project-scoped prompt override changes from two Project.config snapshots."""

    before_entries = _extract_project_prompt_entries(before_config or {})
    after_entries = _extract_project_prompt_entries(after_config or {})
    revisions: list[PromptConfigRevision] = []

    for config_key in sorted(set(before_entries) | set(after_entries)):
        before_entry = before_entries.get(config_key)
        after_entry = after_entries.get(config_key)
        if (before_entry.value if before_entry else None) == (after_entry.value if after_entry else None):
            continue
        source_entry = after_entry or before_entry
        if source_entry is None:
            continue
        revision = await record_prompt_config_revision(
            db,
            scope_type=PROMPT_SCOPE_PROJECT,
            scope_id=project_id,
            config_key=config_key,
            variant_key=source_entry.variant_key,
            value=after_entry.value if after_entry else None,
            created_by=created_by,
            change_source=change_source,
        )
        revisions.append(revision)
    return revisions


async def record_prompt_config_revision(
    db: AsyncSession,
    *,
    scope_type: str,
    scope_id: str | None,
    config_key: str,
    variant_key: str | None,
    value: str | None,
    created_by: str | None = None,
    change_source: str = "manual",
    revision_metadata: Mapping[str, object] | None = None,
    skip_unchanged: bool = True,
) -> PromptConfigRevision:
    """Append a prompt config revision unless the latest stored value is unchanged."""

    normalized_scope_type = str(scope_type or "").strip().lower()
    normalized_scope_id = str(scope_id).strip() if scope_id is not None else None
    normalized_config_key = str(config_key or "").strip()
    normalized_variant = str(variant_key).strip().lower() if variant_key is not None else None
    normalized_value = None if value is None else str(value)
    checksum = _value_checksum(normalized_value)

    latest_revision = await _latest_revision(
        db,
        scope_type=normalized_scope_type,
        scope_id=normalized_scope_id,
        config_key=normalized_config_key,
    )
    if skip_unchanged and latest_revision is not None and latest_revision.value_checksum == checksum:
        return latest_revision

    next_version = 1 if latest_revision is None else int(latest_revision.version or 0) + 1
    revision = PromptConfigRevision(
        scope_type=normalized_scope_type,
        scope_id=normalized_scope_id,
        config_key=normalized_config_key,
        variant_key=normalized_variant,
        version=next_version,
        value=normalized_value,
        value_checksum=checksum,
        change_source=str(change_source or "manual").strip() or "manual",
        created_by=created_by,
        revision_metadata=dict(revision_metadata or {}),
    )
    db.add(revision)
    await db.flush()
    return revision


async def rollback_prompt_config_revision(
    db: AsyncSession,
    *,
    revision_id: str,
    created_by: str | None = None,
) -> PromptConfigRevision:
    """Restore a prompt config revision and append an auditable rollback revision."""

    revision = await db.get(PromptConfigRevision, revision_id)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt config revision not found")
    if revision.scope_type == PROMPT_SCOPE_GLOBAL:
        await _apply_global_revision_value(db, revision)
    elif revision.scope_type == PROMPT_SCOPE_PROJECT:
        await _apply_project_revision_value(db, revision)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported prompt config revision scope")

    return await record_prompt_config_revision(
        db,
        scope_type=revision.scope_type,
        scope_id=revision.scope_id,
        config_key=revision.config_key,
        variant_key=revision.variant_key,
        value=revision.value,
        created_by=created_by,
        change_source=PROMPT_CHANGE_SOURCE_ROLLBACK,
        revision_metadata={
            "rollback_of_revision_id": revision.id,
            "rollback_of_version": revision.version,
        },
        skip_unchanged=False,
    )


async def _latest_revision(
    db: AsyncSession,
    *,
    scope_type: str,
    scope_id: str | None,
    config_key: str,
) -> PromptConfigRevision | None:
    query = select(PromptConfigRevision).where(
        PromptConfigRevision.scope_type == scope_type,
        PromptConfigRevision.config_key == config_key,
    )
    if scope_id is None:
        query = query.where(PromptConfigRevision.scope_id.is_(None))
    else:
        query = query.where(PromptConfigRevision.scope_id == scope_id)
    query = query.order_by(PromptConfigRevision.version.desc())
    return (await db.execute(query)).scalars().first()


def _classify_system_prompt_config_key(config_key: str) -> PromptConfigEntry | None:
    key = str(config_key or "").strip()
    if key == AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY:
        return PromptConfigEntry(config_key=key, variant_key=None, value=None)
    return None


def _extract_project_prompt_entries(config: Mapping[str, object]) -> dict[str, PromptConfigEntry]:
    raw_overrides = config.get(PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY)
    overrides = raw_overrides if isinstance(raw_overrides, Mapping) else {}
    entries: dict[str, PromptConfigEntry] = {}

    routing = normalize_system_prompt_variant_routing(overrides.get("variant_routing") if overrides else None)
    for requested_variant, resolved_variant in routing.items():
        config_key = f"{PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY}.variant_routing.{requested_variant}"
        entries[config_key] = PromptConfigEntry(
            config_key=config_key,
            variant_key=requested_variant,
            value=resolved_variant,
        )

    return entries


async def _apply_global_revision_value(db: AsyncSession, revision: PromptConfigRevision) -> None:
    row = (await db.execute(select(SystemConfig).where(SystemConfig.key == revision.config_key))).scalar_one_or_none()
    if revision.value is None:
        if row is not None:
            await db.delete(row)
            await db.flush()
        return
    if row is None:
        row = SystemConfig(
            key=revision.config_key,
            value=revision.value,
            description=f"Restored from prompt config revision {revision.id}.",
        )
        db.add(row)
    else:
        row.value = revision.value
    await db.flush()


async def _apply_project_revision_value(db: AsyncSession, revision: PromptConfigRevision) -> None:
    if not revision.scope_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project prompt revision is missing scope_id",
        )
    project = await db.get(Project, revision.scope_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    config = dict(project.config or {})
    overrides = dict(config.get(PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY) or {})
    section_name = "variant_routing"
    if not revision.variant_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prompt revision is missing variant_key")

    section = dict(overrides.get(section_name) or {})
    if revision.value is None:
        section.pop(revision.variant_key, None)
    else:
        section[revision.variant_key] = revision.value

    if section:
        overrides[section_name] = section
    else:
        overrides.pop(section_name, None)

    if overrides:
        config[PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY] = overrides
    else:
        config.pop(PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY, None)
    project.config = config
    await db.flush()


def _value_checksum(value: str | None) -> str:
    checksum_input = _DELETED_VALUE_CHECKSUM_INPUT if value is None else value
    return sha256(checksum_input.encode("utf-8")).hexdigest()
