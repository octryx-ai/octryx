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
from .provider_auth import provider_secret_scope

logger = logging.getLogger(__name__)


def resolve_control_plane_default_model(
    provider: LLMProvider | None,
    *,
    config: ControlPlaneConfig | None = None,
    fallback_model_id: str | None = None,
) -> str | None:
    """Resolve the default model for control-plane actions using shared precedence."""

    return resolve_provider_default_model(
        provider,
        config=config,
        fallback_model_id=fallback_model_id,
    )


def resolve_control_plane_promoted_model(
    provider: LLMProvider | None,
    *,
    config: ControlPlaneConfig | None = None,
    fallback_model_id: str | None = None,
) -> str | None:
    """Resolve the model used when promoting a provider into the active runtime chain."""

    for candidate in (
        provider.default_model_id if provider else None,
        config.model_id if config else None,
        fallback_model_id,
    ):
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return None


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


async def ensure_default_control_plane_provider(
    db: AsyncSession,
    *,
    settings: Any,
    infer_provider_runtime_func: Any,
) -> LLMProvider | None:
    access = env_model_access(settings)
    if access is None:
        if problem := env_model_access_problem(settings):
            logger.error("startup.llm_provider_unsupported: %s", problem)
        return None
    provider_name = access.name

    result = await db.execute(
        select(LLMProvider).where(
            LLMProvider.name == provider_name,
            LLMProvider.is_global,
        )
    )
    provider = result.scalars().first()
    if provider:
        return provider

    runtime = infer_provider_runtime_func(name=provider_name, driver=access.driver)
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name=provider_name,
        provider_family=runtime["provider_family"],
        driver=runtime["driver"],
        runtime_kind=runtime["runtime_kind"],
        display_name=access.display_name,
        auth_mode="api_key",
        endpoint_url=access.endpoint_url,
        aws_region=settings.aws_region if access.driver == "bedrock_api" else None,
        aws_role_arn=settings.aws_bedrock_role_arn if access.driver == "bedrock_api" else None,
        # The env bootstrap names its model explicitly (``AGENT_DEFAULT_MODEL``).
        default_model_id=str(settings.agent_default_model or "").strip() or None,
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    bootstrap_api_key = access.api_key or ""
    if bootstrap_api_key:
        await _store_bootstrap_api_key(db, provider, bootstrap_api_key)
    return provider


async def _store_bootstrap_api_key(db: AsyncSession, provider: LLMProvider, bootstrap_api_key: str) -> None:
    # Never persist the key in plaintext: route it through the encrypted
    # secret store and keep only the reference on the provider row.
    from ..secret import set_secret_value

    tool_name, field_name = provider_secret_scope(provider)
    secret_entry = await set_secret_value(
        db,
        tool_name=tool_name,
        field_name=field_name,
        project_id=None,
        value=bootstrap_api_key,
    )
    provider.api_key_secret_ref = secret_entry.id


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
    if not provider:
        return False
    return (
        provider.is_global
        and (provider.display_name or "").endswith("(Default)")
        and provider.name == getattr(env_model_access(settings), "name", "openrouter")
        and target.model_id == provider.default_model_id
    )


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
