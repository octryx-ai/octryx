"""Runtime resolution logic for control-plane prioritized targets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMProvider
from ...models.runtime.llm_provider import LLMModel
from ..model_selection.task_roles import role_tags_by_ref
from .selection_policy import (
    build_environment_fallback_selection_payload,
    build_runtime_selection_payload,
    runtime_selection_is_selected,
)


@dataclass(frozen=True, slots=True)
class _Selection:
    """What every target of one resolution call is judged with."""

    db: AsyncSession
    config: ControlPlaneConfig
    role_tags: dict
    build_provider_client_kwargs_async_func: Callable[..., Any]
    runtime_max_tokens_per_request_func: Callable[..., Any]
    runtime_request_timeout_seconds_func: Callable[..., Any]
    requires_tools: bool
    requires_vision: bool
    include_skipped: bool


async def resolve_control_plane_runtimes(
    db: AsyncSession,
    *,
    runtime_target_id: str | None = None,
    ensure_control_plane_defaults_func,
    environment_model_id: str,
    get_runtime_targets_func,
    build_provider_client_kwargs_async_func,
    build_provider_client_kwargs_func,
    runtime_max_tokens_per_request_func,
    runtime_request_timeout_seconds_func,
    requires_tools: bool = False,
    requires_vision: bool = False,
    include_skipped: bool = False,
) -> list[dict]:
    """
    Read prioritized provider/model runtime config from DB first.
    Falls back to env settings only if no runtime target exists at all; configured
    targets that are all skipped yield an empty list.
    """
    config = await ensure_control_plane_defaults_func(db)
    # The role tags background consumers read are the Task models, not admin-typed target tags.
    role_tags = await role_tags_by_ref(db)
    selection = _Selection(
        db=db, config=config, role_tags=role_tags,
        build_provider_client_kwargs_async_func=build_provider_client_kwargs_async_func,
        runtime_max_tokens_per_request_func=runtime_max_tokens_per_request_func,
        runtime_request_timeout_seconds_func=runtime_request_timeout_seconds_func,
        requires_tools=requires_tools, requires_vision=requires_vision, include_skipped=include_skipped,
    )
    if runtime_target_id:
        explicit_with_fallbacks = await _explicit_target_runtimes(
            selection, runtime_target_id, get_runtime_targets_func=get_runtime_targets_func
        )
        if explicit_with_fallbacks:
            return explicit_with_fallbacks

    targets = await get_runtime_targets_func(db, config, active_only=True)
    runtimes = []
    if targets:
        runtimes = await _target_runtimes(selection, targets)

    if runtimes:
        return runtimes
    # Configured targets that were all skipped (readiness, capability, client
    # configuration) fail closed: substituting the unscoped environment runtime
    # would bypass provider intent and project runtime allowlists. Callers get an
    # empty list and can re-resolve with ``include_skipped=True`` for reasons.
    if targets or await get_runtime_targets_func(db, config, active_only=False):
        return []

    client_kwargs = build_provider_client_kwargs_func(None)
    return [build_environment_fallback_selection_payload(client_kwargs=client_kwargs, model_id=environment_model_id)]


async def _explicit_target_runtimes(
    selection: _Selection, runtime_target_id: str, *, get_runtime_targets_func
) -> list[dict]:
    """The explicitly chosen target first, then the other active targets as its fallbacks."""
    db, config = selection.db, selection.config
    target = await db.get(ControlPlaneRuntimeTarget, runtime_target_id)
    if not (target and target.config_id == config.id and target.is_active):
        return []
    provider = await db.get(LLMProvider, target.provider_id, options=[selectinload(LLMProvider.oauth_config)])
    if not (provider and provider.is_active):
        return []
    active_targets = await get_runtime_targets_func(db, config, active_only=True)
    ordered_targets = [target, *[item for item in active_targets if item.id != target.id]]
    return await _target_runtimes(selection, ordered_targets)


async def _target_runtimes(selection: _Selection, targets: list) -> list[dict]:
    """The selection payload of each target with an active provider, in the given order."""
    provider_map, model_map = await _providers_and_models(selection.db, targets)
    runtimes: list[dict] = []
    for target in targets:
        provider = provider_map.get(target.provider_id)
        if not provider or not provider.is_active:
            continue
        payload = await _target_payload(selection, target, provider, model_map.get((target.provider_id,
                                                                                     target.model_id)))
        if payload is not None:
            runtimes.append(payload)
    return runtimes


async def _providers_and_models(
    db: AsyncSession, targets: list
) -> tuple[dict[str, LLMProvider], dict[tuple[str, str], LLMModel]]:
    provider_ids = {target.provider_id for target in targets}
    providers_result = await db.execute(
        select(LLMProvider).options(selectinload(LLMProvider.oauth_config)).where(LLMProvider.id.in_(provider_ids))
    )
    provider_map = {provider.id: provider for provider in providers_result.scalars().all()}

    model_keys = {(target.provider_id, target.model_id) for target in targets}
    model_map: dict[tuple[str, str], LLMModel] = {}
    if model_keys:
        models_result = await db.execute(
            select(LLMModel).where(tuple_(LLMModel.provider_id, LLMModel.model_id).in_(list(model_keys)))
        )
        model_map = {(model.provider_id, model.model_id): model for model in models_result.scalars().all()}
    return provider_map, model_map


async def _target_payload(
    selection: _Selection, target: Any, provider: LLMProvider, model: LLMModel | None
) -> dict | None:
    """One target's payload; ``None`` when it is skipped and skipped targets are not wanted."""
    max_tokens_per_request = selection.runtime_max_tokens_per_request_func(provider, model, selection.config)
    request_timeout_seconds = selection.runtime_request_timeout_seconds_func(provider)

    def payload(client_kwargs: dict, **extra: Any) -> dict:
        return build_runtime_selection_payload(
            client_kwargs=client_kwargs,
            provider=provider,
            target=target,
            model=model,
            model_id=target.model_id,
            priority=target.priority,
            use_case_tags=selection.role_tags.get((target.provider_id, target.model_id), []),
            max_tokens_per_request=max_tokens_per_request,
            request_timeout_seconds=request_timeout_seconds,
            requires_tools=selection.requires_tools,
            requires_vision=selection.requires_vision,
            **extra,
        )

    candidate_payload = payload(_runtime_identity_kwargs(provider))
    if not runtime_selection_is_selected(candidate_payload):
        return candidate_payload if selection.include_skipped else None
    try:
        client_kwargs = await selection.build_provider_client_kwargs_async_func(selection.db, provider)
    except Exception:
        if selection.include_skipped:
            return payload(_runtime_identity_kwargs(provider), client_configuration_available=False)
        return None
    return payload(client_kwargs)


async def resolve_control_plane_runtime(db: AsyncSession, *, resolve_control_plane_runtimes_func) -> dict:
    runtimes = await resolve_control_plane_runtimes_func(db)
    if not runtimes:
        raise RuntimeError("No configured runtime target is ready for execution")
    return runtimes[0]


def _runtime_identity_kwargs(provider: LLMProvider) -> dict:
    return {
        "provider_name": provider.name,
        "driver": provider.driver,
        "provider_family": provider.provider_family,
        "runtime_kind": provider.runtime_kind,
        "auth_mode": provider.auth_mode,
    }
