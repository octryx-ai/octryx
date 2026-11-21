"""Runtime target mutation operations for control plane."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ControlPlaneRuntimeTarget, LLMProvider


async def upsert_runtime_target(
    db: AsyncSession,
    *,
    provider: LLMProvider,
    model_id: str,
    make_primary: bool = False,
    is_active: bool = True,
    get_or_create_control_plane_config_func: Any,
    get_runtime_targets_func: Any,
    is_seed_runtime_target_func: Any,
    resequence_runtime_targets_func: Any,
    sync_primary_runtime_target_func: Any,
) -> ControlPlaneRuntimeTarget:
    config = await get_or_create_control_plane_config_func(db)
    normalized_model_id = model_id.strip()
    existing_targets = await get_runtime_targets_func(db, config)
    if len(existing_targets) == 1:
        await _drop_replaced_seed_target(
            db,
            existing_targets[0],
            provider=provider,
            normalized_model_id=normalized_model_id,
            is_seed_runtime_target_func=is_seed_runtime_target_func,
        )

    result = await db.execute(
        select(ControlPlaneRuntimeTarget).where(
            ControlPlaneRuntimeTarget.config_id == config.id,
            ControlPlaneRuntimeTarget.provider_id == provider.id,
            ControlPlaneRuntimeTarget.model_id == normalized_model_id,
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        targets = await get_runtime_targets_func(db, config)
        target = ControlPlaneRuntimeTarget(
            id=str(uuid.uuid4()),
            config_id=config.id,
            provider_id=provider.id,
            model_id=normalized_model_id,
            priority=len(targets) + 1,
            is_active=is_active,
        )
        db.add(target)
    else:
        target.is_active = is_active

    provider.default_model_id = normalized_model_id
    await db.flush()

    if make_primary:
        await _make_primary(db, config, target, get_runtime_targets_func=get_runtime_targets_func)

    await resequence_runtime_targets_func(db, config)
    await sync_primary_runtime_target_func(db, config)
    return target


async def _drop_replaced_seed_target(
    db: AsyncSession,
    existing_target: ControlPlaneRuntimeTarget,
    *,
    provider: LLMProvider,
    normalized_model_id: str,
    is_seed_runtime_target_func: Any,
) -> None:
    """The lone seed target gives way to the first real target, unless it is that very target."""
    seed_provider = await db.get(LLMProvider, existing_target.provider_id)
    if is_seed_runtime_target_func(existing_target, seed_provider):
        same_seed_target = (
            existing_target.provider_id == provider.id and existing_target.model_id == normalized_model_id
        )
        if not same_seed_target:
            await db.delete(existing_target)
            await db.flush()


async def _make_primary(
    db: AsyncSession,
    config: Any,
    target: ControlPlaneRuntimeTarget,
    *,
    get_runtime_targets_func: Any,
) -> None:
    targets = await get_runtime_targets_func(db, config)
    for item in targets:
        if item.id == target.id:
            item.priority = 0
        else:
            item.priority += 1
    await db.flush()


async def move_runtime_target(
    db: AsyncSession,
    target_id: str,
    direction: str,
    *,
    get_runtime_targets_func: Any,
    get_or_create_control_plane_config_func: Any,
    resequence_runtime_targets_func: Any,
    sync_primary_runtime_target_func: Any,
) -> ControlPlaneRuntimeTarget | None:
    target = await db.get(ControlPlaneRuntimeTarget, target_id)
    if not target:
        return None

    targets = await get_runtime_targets_func(db)
    index_by_id = {item.id: index for index, item in enumerate(targets)}
    current_index = index_by_id[target.id]
    if direction == "up" and current_index > 0:
        swap_index = current_index - 1
    elif direction == "down" and current_index < len(targets) - 1:
        swap_index = current_index + 1
    else:
        return target

    other = targets[swap_index]
    target.priority, other.priority = other.priority, target.priority
    await db.flush()
    config = await get_or_create_control_plane_config_func(db)
    await resequence_runtime_targets_func(db, config)
    await sync_primary_runtime_target_func(db, config)
    return target


async def delete_runtime_target(
    db: AsyncSession,
    target_id: str,
    *,
    get_or_create_control_plane_config_func: Any,
    ensure_default_runtime_target_func: Any,
    resequence_runtime_targets_func: Any,
    sync_primary_runtime_target_func: Any,
) -> bool:
    target = await db.get(ControlPlaneRuntimeTarget, target_id)
    if not target:
        return False
    config = await get_or_create_control_plane_config_func(db)
    await db.delete(target)
    await db.flush()
    await ensure_default_runtime_target_func(db, config)
    await resequence_runtime_targets_func(db, config)
    await sync_primary_runtime_target_func(db, config)
    return True


async def toggle_runtime_target(
    db: AsyncSession,
    target_id: str,
    *,
    get_or_create_control_plane_config_func: Any,
    ensure_default_runtime_target_func: Any,
    resequence_runtime_targets_func: Any,
    sync_primary_runtime_target_func: Any,
) -> ControlPlaneRuntimeTarget | None:
    target = await db.get(ControlPlaneRuntimeTarget, target_id)
    if not target:
        return None
    target.is_active = not target.is_active
    await db.flush()
    config = await get_or_create_control_plane_config_func(db)
    await ensure_default_runtime_target_func(db, config)
    await resequence_runtime_targets_func(db, config)
    await sync_primary_runtime_target_func(db, config)
    return target
