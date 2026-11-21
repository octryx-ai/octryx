from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ExecPolicyConfig
from .policy_config import _copy_default_exec_policy_config, normalize_exec_policy_config, with_removed_defaults


async def get_global_exec_policy_config(db: AsyncSession) -> ExecPolicyConfig | None:
    query = (
        select(ExecPolicyConfig)
        .where(
            ExecPolicyConfig.project_id.is_(None),
            ExecPolicyConfig.is_active,
        )
        .order_by(ExecPolicyConfig.priority.asc(), ExecPolicyConfig.created_at.asc())
    )
    return (await db.execute(query)).scalars().first()


async def list_global_exec_policy_configs(db: AsyncSession) -> list[ExecPolicyConfig]:
    query = (
        select(ExecPolicyConfig)
        .where(
            ExecPolicyConfig.project_id.is_(None),
            ExecPolicyConfig.is_active,
        )
        .order_by(ExecPolicyConfig.priority.asc(), ExecPolicyConfig.created_at.asc())
    )
    return (await db.execute(query)).scalars().all()


async def ensure_default_exec_policy_config(db: AsyncSession) -> ExecPolicyConfig:
    existing = await get_global_exec_policy_config(db)
    if existing is not None:
        return existing

    created = ExecPolicyConfig(
        id=str(uuid.uuid4()),
        name="Global Exec Policy",
        project_id=None,
        priority=100,
        is_active=True,
        config_json=with_removed_defaults(_copy_default_exec_policy_config()),
    )
    db.add(created)
    await db.flush()
    return created



async def get_effective_exec_policy_config(
    db: AsyncSession | None,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    if db is None:
        return _copy_default_exec_policy_config()

    await ensure_default_exec_policy_config(db)
    effective = _copy_default_exec_policy_config()
    for config in await list_global_exec_policy_configs(db):
        effective = normalize_exec_policy_config(config.config_json, base_config=effective)
    if project_id is None:
        return effective

    project_query = (
        select(ExecPolicyConfig)
        .where(
            ExecPolicyConfig.is_active,
            ExecPolicyConfig.project_id == project_id,
        )
        .order_by(ExecPolicyConfig.priority.asc(), ExecPolicyConfig.created_at.asc())
    )
    for config in (await db.execute(project_query)).scalars().all():
        effective = normalize_exec_policy_config(config.config_json, base_config=effective)
    return effective


async def list_exec_policy_configs(db: AsyncSession) -> list[ExecPolicyConfig]:
    return (
        (
            await db.execute(
                select(ExecPolicyConfig).order_by(
                    ExecPolicyConfig.priority.asc(),
                    ExecPolicyConfig.created_at.asc(),
                )
            )
        )
        .scalars()
        .all()
    )


async def upsert_global_exec_policy_config(db: AsyncSession, config_json: dict[str, Any]) -> ExecPolicyConfig:
    existing = await get_global_exec_policy_config(db)
    base_config = existing.config_json if existing is not None else _copy_default_exec_policy_config()
    normalized = normalize_exec_policy_config(with_removed_defaults(config_json), base_config=base_config)
    if existing is None:
        existing = ExecPolicyConfig(
            id=str(uuid.uuid4()),
            name="Global Exec Policy",
            project_id=None,
            priority=100,
            is_active=True,
            config_json=normalized,
        )
        db.add(existing)
    else:
        existing.config_json = normalized
        existing.is_active = True
    await db.flush()
    return existing


async def upsert_exec_policy_config(
    db: AsyncSession,
    *,
    config_id: str | None,
    name: str,
    project_id: str | None,
    priority: int,
    is_active: bool,
    config_json: dict[str, Any],
) -> ExecPolicyConfig:
    existing: ExecPolicyConfig | None = None
    if config_id:
        existing = await db.get(ExecPolicyConfig, config_id)
    if project_id is None:
        return await upsert_global_exec_policy_config(db, config_json)
    if existing is None:
        default_row = await ensure_default_exec_policy_config(db)
        base_config = default_row.config_json
    else:
        base_config = existing.config_json
    normalized = normalize_exec_policy_config(with_removed_defaults(config_json), base_config=base_config)
    if existing is None:
        existing = ExecPolicyConfig(
            id=config_id or str(uuid.uuid4()),
            name=name.strip() or "Exec Policy",
            project_id=project_id or None,
            priority=priority,
            is_active=is_active,
            config_json=normalized,
        )
        db.add(existing)
    else:
        existing.name = name.strip() or existing.name or "Exec Policy"
        existing.project_id = project_id or None
        existing.priority = priority
        existing.is_active = is_active
        existing.config_json = normalized
    await db.flush()
    return existing


async def delete_exec_policy_config(db: AsyncSession, config_id: str) -> bool:
    existing = await db.get(ExecPolicyConfig, config_id)
    if existing is None:
        return False
    await db.delete(existing)
    await db.flush()
    return True


# The public names of this module (callers and tests import them).
__all__ = [
    "delete_exec_policy_config",
    "ensure_default_exec_policy_config",
    "get_effective_exec_policy_config",
    "get_global_exec_policy_config",
    "list_exec_policy_configs",
    "list_global_exec_policy_configs",
    "upsert_exec_policy_config",
    "upsert_global_exec_policy_config",
]
