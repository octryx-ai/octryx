"""Control-plane config and runtime-target ordering defaults."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMProvider
from ..provider_runtime_config import resolve_provider_default_model
from .env_model_access import env_model_access, env_model_access_problem

logger = logging.getLogger(__name__)


def resolve_control_plane_default_model(
    provider: LLMProvider | None,
    *,
    config: ControlPlaneConfig | None = None,
    fallback_model_id: str | None = None,
) -> str | None:
    return resolve_provider_default_model(
        provider,
        config=config,
        fallback_model_id=fallback_model_id,
    )



async def get_or_create_control_plane_config(
    db: AsyncSession,
    *,
    get_agent_default_model_func: Any,
) -> ControlPlaneConfig:
    result = await db.execute(select(ControlPlaneConfig).where(ControlPlaneConfig.name == "default"))
    config = result.scalar_one_or_none()
    if config:
        return config

    config = ControlPlaneConfig(
        id=str(uuid.uuid4()),
        name="default",
        model_id=await get_agent_default_model_func(db),
        is_active=True,
    )
    db.add(config)
    await db.flush()
    return config


_ROUTE_FAILURES_LOGGED: set[str] = set()


async def ensure_default_control_plane_provider(
    db: AsyncSession,
    *,
    settings: Any,
    infer_provider_runtime_func: Any,
) -> LLMProvider | None:
    # The bundled LiteLLM provider with the environment's model as a route and the default (``env_model_access``).
    from ..model_gateway.bundled_litellm import register_bundled_provider
    from ..model_gateway.bundled_routes import ensure_route

    access = env_model_access(settings)
    if access is None:
        if problem := env_model_access_problem(settings):
            logger.error("startup.llm_provider_unsupported: %s", problem)
        return None
    try:
        provider = await register_bundled_provider(db)
        if provider is None:
            logger.error("startup.llm_provider_without_bundled_litellm: LLM_PROVIDER needs the bundled LiteLLM")
            return None
        await ensure_route(db, access)
    except Exception as error:
        # Retried on every call that finds no runtime target, so the cause is logged in full once per process.
        failure = f"{access.alias}:{type(error).__name__}"
        if failure in _ROUTE_FAILURES_LOGGED:
            logger.debug("startup.llm_provider_route_failed again (alias=%s)", access.alias)
        else:
            _ROUTE_FAILURES_LOGGED.add(failure)
            logger.exception("startup.llm_provider_route_failed")
        return None
    provider.default_model_id = access.alias
    await db.flush()
    return provider


async def get_runtime_targets(
    db: AsyncSession,
    config: ControlPlaneConfig | None = None,
    *,
    active_only: bool = False,
    get_or_create_control_plane_config_func: Any,
) -> list[ControlPlaneRuntimeTarget]:
    config = config or await get_or_create_control_plane_config_func(db)
    stmt = (
        select(ControlPlaneRuntimeTarget)
        .where(ControlPlaneRuntimeTarget.config_id == config.id)
        .order_by(ControlPlaneRuntimeTarget.priority.asc(), ControlPlaneRuntimeTarget.created_at.asc())
    )
    if active_only:
        stmt = stmt.where(ControlPlaneRuntimeTarget.is_active)
    result = await db.execute(stmt)
    return result.scalars().all()


async def resequence_runtime_targets(
    db: AsyncSession,
    config: ControlPlaneConfig | None = None,
    *,
    get_runtime_targets_func: Any,
) -> list[ControlPlaneRuntimeTarget]:
    targets = await get_runtime_targets_func(db, config)
    for index, target in enumerate(targets, start=1):
        target.priority = index
    await db.flush()
    return targets


async def sync_primary_runtime_target(
    db: AsyncSession,
    config: ControlPlaneConfig | None = None,
    *,
    get_or_create_control_plane_config_func: Any,
    get_runtime_targets_func: Any,
    get_agent_default_model_func: Any,
) -> ControlPlaneConfig:
    config = config or await get_or_create_control_plane_config_func(db)
    active_targets = await get_runtime_targets_func(db, config, active_only=True)
    primary_target = active_targets[0] if active_targets else None
    if primary_target:
        config.provider_id = primary_target.provider_id
        config.model_id = primary_target.model_id
    else:
        config.provider_id = None
        config.model_id = await get_agent_default_model_func(db)
    await db.flush()
    return config


async def ensure_default_runtime_target(
    db: AsyncSession,
    config: ControlPlaneConfig,
    *,
    get_runtime_targets_func: Any,
    resequence_runtime_targets_func: Any,
    sync_primary_runtime_target_func: Any,
    ensure_default_control_plane_provider_func: Any,
) -> None:
    targets = await get_runtime_targets_func(db, config)
    if targets:
        await resequence_runtime_targets_func(db, config)
        await sync_primary_runtime_target_func(db, config)
        return

    provider = None
    if config.provider_id:
        provider = await db.get(LLMProvider, config.provider_id)
    if not provider:
        provider = await ensure_default_control_plane_provider_func(db)
    if not provider:
        return

    model_id = resolve_control_plane_default_model(provider, config=config)
    if not model_id:
        # No model is named anywhere: the install needs a configured runtime target.
        return
    target = ControlPlaneRuntimeTarget(
        id=str(uuid.uuid4()),
        config_id=config.id,
        provider_id=provider.id,
        model_id=model_id,
        priority=1,
        is_active=True,
    )
    db.add(target)
    provider.default_model_id = model_id
    await db.flush()
    # The first start's model gets its dated list price, so cost caps count it from the first turn.
    from ..budget.list_prices import apply_list_price

    await apply_list_price(db, provider_id=provider.id, model_id=model_id)
    await resequence_runtime_targets_func(db, config)
    await sync_primary_runtime_target_func(db, config)


def is_seed_runtime_target(target: ControlPlaneRuntimeTarget, provider: LLMProvider | None, *, settings: Any) -> bool:
    from ..model_gateway.bundled_litellm import PROVIDER_NAME

    access = env_model_access(settings)
    return bool(provider and access and provider.name == PROVIDER_NAME and target.model_id == access.alias)


async def ensure_control_plane_defaults(
    db: AsyncSession,
    *,
    get_or_create_control_plane_config_func: Any,
    ensure_default_runtime_target_func: Any,
    get_agent_default_model_func: Any,
) -> ControlPlaneConfig:
    config = await get_or_create_control_plane_config_func(db)
    await ensure_default_runtime_target_func(db, config)
    if not config.model_id:
        config.model_id = await get_agent_default_model_func(db)
    return config
