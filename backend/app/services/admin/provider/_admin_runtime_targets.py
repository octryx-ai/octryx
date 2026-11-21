"""Context budget and runtime target CRUD."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from ...context_budget import (
    delete_context_budget_profile,
    list_context_budget_profiles,
    upsert_context_budget_profile,
)
from ...policy_lists.errors import PolicyListError, as_http_exception
from ...policy_lists.model_capabilities import validate_runtime_capability_tags

# ``temperature_support`` -> ``ControlPlaneRuntimeTarget.accepts_temperature`` (None = sampling catalog).
_TEMPERATURE_SUPPORT: dict[str, bool | None] = {"catalog": None, "accepts": True, "rejects": False}


async def get_context_budget_profiles(db: AsyncSession) -> list[dict[str, Any]]:
    return await list_context_budget_profiles(db)


async def save_context_budget_profile(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return await upsert_context_budget_profile(
        db,
        profile_id=payload.get("id"),
        name=str(payload.get("name") or ""),
        trigger_pattern=str(payload.get("trigger_pattern") or ""),
        base_budget=int(payload.get("base_budget") or 0),
        tool_budget=int(payload.get("tool_budget") or 0),
        history_budget=int(payload.get("history_budget") or 0),
        entity_budget=int(payload.get("entity_budget") or 0),
        memory_budget=int(payload.get("memory_budget") or 0),
        priority=int(payload.get("priority") or 0),
        is_active=bool(payload.get("is_active", True)),
    )


async def remove_context_budget_profile(
    db: AsyncSession,
    *,
    profile_id: str,
) -> list[dict[str, Any]]:
    await delete_context_budget_profile(db, profile_id=profile_id)
    return await list_context_budget_profiles(db)


async def list_runtimes(
    db: AsyncSession,
    *,
    get_runtime_targets_func: Callable[..., Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    targets = await get_runtime_targets_func(db)
    payloads: list[dict[str, Any]] = []
    for target in targets:
        provider = await db.get(LLMProvider, target.provider_id)
        model = await _get_runtime_model(db, target)
        payloads.append(serialize_runtime_target(target, provider, model))
    return payloads


async def add_runtime(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    upsert_runtime_target_func: Callable[..., Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    provider_id = str(payload.get("provider_id") or "").strip()
    model_id_val = str(payload.get("model_id") or "").strip()
    make_primary = bool(payload.get("make_primary", False))
    if not provider_id or not model_id_val:
        raise HTTPException(status_code=400, detail="provider_id and model_id are required")
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    target = await upsert_runtime_target_func(
        db,
        provider=provider,
        model_id=model_id_val,
        make_primary=make_primary,
        is_active=True,
    )
    if "use_case_tags" in payload:
        target.use_case_tags = payload["use_case_tags"]
    if payload.get("capability_tags") is not None:
        target.capability_tags = await _capability_tags(db, payload["capability_tags"])
    if payload.get("temperature_support") is not None:
        target.accepts_temperature = _TEMPERATURE_SUPPORT[payload["temperature_support"]]
    await db.commit()
    model = await _get_runtime_model(db, target)
    return serialize_runtime_target(target, provider, model)


async def move_runtime(
    db: AsyncSession,
    *,
    target_id: str,
    direction: str,
    move_runtime_target_func: Callable[..., Any],
    get_runtime_targets_func: Callable[..., Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    await move_runtime_target_func(db, target_id, direction)
    await db.commit()
    return await list_runtimes(
        db,
        get_runtime_targets_func=get_runtime_targets_func,
        serialize_runtime_target=serialize_runtime_target,
    )


async def toggle_runtime(
    db: AsyncSession,
    *,
    target_id: str,
    toggle_runtime_target_func: Callable[..., Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    await toggle_runtime_target_func(db, target_id)
    await db.commit()
    target = await db.get(ControlPlaneRuntimeTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Runtime target not found")
    provider = await db.get(LLMProvider, target.provider_id)
    model = await _get_runtime_model(db, target)
    return serialize_runtime_target(target, provider, model)


async def update_runtime(
    db: AsyncSession,
    *,
    target_id: str,
    payload: dict[str, Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    target = await db.get(ControlPlaneRuntimeTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Runtime target not found")
    if "use_case_tags" in payload:
        target.use_case_tags = payload["use_case_tags"]
    if payload.get("capability_tags") is not None:
        target.capability_tags = await _capability_tags(db, payload["capability_tags"])
    if payload.get("temperature_support") is not None:
        target.accepts_temperature = _TEMPERATURE_SUPPORT[payload["temperature_support"]]
    if "is_active" in payload:
        target.is_active = bool(payload["is_active"])
    if "model_id" in payload:
        target.model_id = str(payload["model_id"]).strip()
    provider = await db.get(LLMProvider, target.provider_id)
    await db.commit()
    model = await _get_runtime_model(db, target)
    return serialize_runtime_target(target, provider, model)


async def delete_runtime(
    db: AsyncSession,
    *,
    target_id: str,
    delete_runtime_target_func: Callable[..., Any],
) -> dict[str, Any]:
    await delete_runtime_target_func(db, target_id)
    await db.commit()
    return {"status": "deleted"}


async def _capability_tags(db: AsyncSession, raw: Any) -> list[str]:
    """Governed capability tags: unknown capabilities are refused with ``unknown_capability``."""
    try:
        return await validate_runtime_capability_tags(db, raw)
    except PolicyListError as error:
        raise as_http_exception(error) from None


async def _get_runtime_model(db: AsyncSession, target: ControlPlaneRuntimeTarget) -> LLMModel | None:
    return (
        await db.execute(
            select(LLMModel).where(
                LLMModel.provider_id == target.provider_id,
                LLMModel.model_id == target.model_id,
            )
        )
    ).scalar_one_or_none()
