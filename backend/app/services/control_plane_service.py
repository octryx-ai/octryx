"""Control plane provider/model configuration resolved from the database."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.control_plane.client_kwargs import (
    build_provider_client_kwargs as _build_provider_client_kwargs_impl,
)
from app.services.control_plane.client_kwargs import (
    build_provider_client_kwargs_async as _build_provider_client_kwargs_async_impl,
)
from app.services.control_plane.config import (
    ensure_control_plane_defaults as _ensure_control_plane_defaults_impl,
)
from app.services.control_plane.config import (
    ensure_default_control_plane_provider as _ensure_default_control_plane_provider_impl,
)
from app.services.control_plane.config import (
    ensure_default_runtime_target as _ensure_default_runtime_target_impl,
)
from app.services.control_plane.config import (
    get_or_create_control_plane_config as _get_or_create_control_plane_config_impl,
)
from app.services.control_plane.config import (
    get_runtime_targets as _get_runtime_targets_impl,
)
from app.services.control_plane.config import (
    resequence_runtime_targets as _resequence_runtime_targets_impl,
)
from app.services.control_plane.config import (
    sync_primary_runtime_target as _sync_primary_runtime_target_impl,
)
from app.services.control_plane.constants import (
    settings,
)
from app.services.control_plane.provider_auth import get_provider_auth_mode
from app.services.control_plane.provider_auth import (
    resolve_provider_api_key as _resolve_provider_api_key_impl,
)
from app.services.control_plane.resolution import (
    resolve_control_plane_runtime as _resolve_control_plane_runtime_impl,
)
from app.services.control_plane.resolution import (
    resolve_control_plane_runtimes as _resolve_control_plane_runtimes_impl,
)
from app.services.control_plane.runtime_limits import runtime_max_tokens_per_request
from app.services.control_plane.service_helpers import (
    _is_seed_runtime_target,
    _runtime_request_timeout_seconds,
)
from app.services.control_plane.targets import (
    delete_runtime_target as _delete_runtime_target_impl,
)
from app.services.control_plane.targets import (
    move_runtime_target as _move_runtime_target_impl,
)
from app.services.control_plane.targets import (
    toggle_runtime_target as _toggle_runtime_target_impl,
)
from app.services.control_plane.targets import (
    upsert_runtime_target as _upsert_runtime_target_impl,
)

from ..agent.providers import infer_provider_runtime
from ..models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMProvider
from .secret import get_secret_value
from .system_config import get_agent_default_model


async def resolve_provider_api_key(db: AsyncSession, provider: LLMProvider | None) -> str | None:
    return await _resolve_provider_api_key_impl(
        db,
        provider,
        settings=settings,
        get_secret_value_func=get_secret_value,
    )


async def get_or_create_control_plane_config(db: AsyncSession) -> ControlPlaneConfig:
    return await _get_or_create_control_plane_config_impl(
        db,
        get_agent_default_model_func=get_agent_default_model,
    )


async def ensure_default_control_plane_provider(db: AsyncSession) -> LLMProvider | None:
    return await _ensure_default_control_plane_provider_impl(
        db,
        settings=settings,
        infer_provider_runtime_func=infer_provider_runtime,
    )


async def get_runtime_targets(
    db: AsyncSession,
    config: ControlPlaneConfig | None = None,
    *,
    active_only: bool = False,
) -> list[ControlPlaneRuntimeTarget]:
    return await _get_runtime_targets_impl(
        db,
        config,
        active_only=active_only,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
    )


async def resequence_runtime_targets(
    db: AsyncSession,
    config: ControlPlaneConfig | None = None,
) -> list[ControlPlaneRuntimeTarget]:
    return await _resequence_runtime_targets_impl(
        db,
        config,
        get_runtime_targets_func=get_runtime_targets,
    )


async def sync_primary_runtime_target(db: AsyncSession, config: ControlPlaneConfig | None = None) -> ControlPlaneConfig:
    return await _sync_primary_runtime_target_impl(
        db,
        config,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
        get_runtime_targets_func=get_runtime_targets,
        get_agent_default_model_func=get_agent_default_model,
    )


async def ensure_default_runtime_target(db: AsyncSession, config: ControlPlaneConfig) -> None:
    await _ensure_default_runtime_target_impl(
        db,
        config,
        get_runtime_targets_func=get_runtime_targets,
        resequence_runtime_targets_func=resequence_runtime_targets,
        sync_primary_runtime_target_func=sync_primary_runtime_target,
        ensure_default_control_plane_provider_func=ensure_default_control_plane_provider,
    )


async def ensure_control_plane_defaults(db: AsyncSession) -> ControlPlaneConfig:
    return await _ensure_control_plane_defaults_impl(
        db,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
        ensure_default_runtime_target_func=ensure_default_runtime_target,
        get_agent_default_model_func=get_agent_default_model,
    )


def build_provider_client_kwargs(provider: LLMProvider | None) -> dict:
    return _build_provider_client_kwargs_impl(
        provider,
        settings=settings,
        infer_provider_runtime_func=infer_provider_runtime,
        get_provider_auth_mode_func=get_provider_auth_mode,
    )


async def build_provider_client_kwargs_async(db: AsyncSession, provider: LLMProvider | None) -> dict:
    return await _build_provider_client_kwargs_async_impl(
        db,
        provider,
        build_provider_client_kwargs_func=build_provider_client_kwargs,
        get_secret_value_func=get_secret_value,
    )


async def upsert_runtime_target(
    db: AsyncSession,
    *,
    provider: LLMProvider,
    model_id: str,
    make_primary: bool = False,
    is_active: bool = True,
) -> ControlPlaneRuntimeTarget:
    return await _upsert_runtime_target_impl(
        db,
        provider=provider,
        model_id=model_id,
        make_primary=make_primary,
        is_active=is_active,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
        get_runtime_targets_func=get_runtime_targets,
        is_seed_runtime_target_func=_is_seed_runtime_target,
        resequence_runtime_targets_func=resequence_runtime_targets,
        sync_primary_runtime_target_func=sync_primary_runtime_target,
    )


async def move_runtime_target(
    db: AsyncSession,
    target_id: str,
    direction: str,
) -> ControlPlaneRuntimeTarget | None:
    return await _move_runtime_target_impl(
        db,
        target_id,
        direction,
        get_runtime_targets_func=get_runtime_targets,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
        resequence_runtime_targets_func=resequence_runtime_targets,
        sync_primary_runtime_target_func=sync_primary_runtime_target,
    )


async def delete_runtime_target(db: AsyncSession, target_id: str) -> bool:
    return await _delete_runtime_target_impl(
        db,
        target_id,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
        ensure_default_runtime_target_func=ensure_default_runtime_target,
        resequence_runtime_targets_func=resequence_runtime_targets,
        sync_primary_runtime_target_func=sync_primary_runtime_target,
    )


async def toggle_runtime_target(db: AsyncSession, target_id: str) -> ControlPlaneRuntimeTarget | None:
    return await _toggle_runtime_target_impl(
        db,
        target_id,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
        ensure_default_runtime_target_func=ensure_default_runtime_target,
        resequence_runtime_targets_func=resequence_runtime_targets,
        sync_primary_runtime_target_func=sync_primary_runtime_target,
    )


async def resolve_control_plane_runtimes(
    db: AsyncSession,
    *,
    runtime_target_id: str | None = None,
    requires_tools: bool = False,
    requires_vision: bool = False,
    include_skipped: bool = False,
) -> list[dict]:
    return await _resolve_control_plane_runtimes_impl(
        db,
        runtime_target_id=runtime_target_id,
        requires_tools=requires_tools,
        requires_vision=requires_vision,
        include_skipped=include_skipped,
        ensure_control_plane_defaults_func=ensure_control_plane_defaults,
        # No runtime target exists at all: the environment's declared model (``AGENT_DEFAULT_MODEL``).
        environment_model_id=str(settings.agent_default_model or "").strip(),
        get_runtime_targets_func=get_runtime_targets,
        build_provider_client_kwargs_async_func=build_provider_client_kwargs_async,
        build_provider_client_kwargs_func=build_provider_client_kwargs,
        runtime_max_tokens_per_request_func=runtime_max_tokens_per_request,
        runtime_request_timeout_seconds_func=_runtime_request_timeout_seconds,
    )


async def resolve_control_plane_runtime(db: AsyncSession) -> dict:
    return await _resolve_control_plane_runtime_impl(
        db,
        resolve_control_plane_runtimes_func=resolve_control_plane_runtimes,
    )
