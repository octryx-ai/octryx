"""The platform order and the fallback mode (Runtime → Models → Default & fallback).

The platform order is the active runtime targets of the active control-plane configuration, by priority. #1 is the
platform default: it runs when nobody chose a model. The same order is the fallback order. Each entry is a Model
catalog row, named by its ``catalog_key``; a target is the "this model is in the order" fact (order + enabled).

Saving the order rewrites only the targets: listed models get priority 1..n and are active (a missing target is
created), every other target of the configuration is deactivated, never deleted (its history stays readable).

The fallback mode keeps its stored values (``agent.runtime_fallback_mode``): ``all_runtimes`` = "Try the next
allowed model", ``first_runtime_only`` = "Stop with an error". Unset means "next allowed" for every driver.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.core.runtime.runtime_fallback_policy import (
    RUNTIME_FALLBACK_MODE_ALL_RUNTIMES,
    RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY,
)
from ...models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from ..system_config import AGENT_RUNTIME_FALLBACK_MODE_KEY, get_system_config_value, set_system_config_value

FALLBACK_NEXT = "next"
FALLBACK_STOP = "stop"
FALLBACK_CHOICES = (FALLBACK_NEXT, FALLBACK_STOP)
_STORED_MODE = {
    FALLBACK_NEXT: RUNTIME_FALLBACK_MODE_ALL_RUNTIMES,
    FALLBACK_STOP: RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY,
}
MAX_ORDER = 50

ERROR_ORDER_INVALID = "model_order_invalid"
ERROR_ORDER_EMPTY = "model_order_empty"
ERROR_ORDER_UNKNOWN_MODEL = "model_order_unknown_model"
ERROR_ORDER_MODEL_OFF = "model_order_model_not_enabled"
ERROR_FALLBACK_INVALID = "model_fallback_invalid"


class ModelOrderError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def fallback_choice(stored: str | None) -> str:
    """The page's choice for a stored mode; unset (or unknown) reads as "next allowed"."""
    stop = str(stored or "").strip().lower() == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY
    return FALLBACK_STOP if stop else FALLBACK_NEXT


async def active_config(db: AsyncSession, *, create: bool = False) -> ControlPlaneConfig | None:
    config = (
        await db.execute(
            select(ControlPlaneConfig).where(ControlPlaneConfig.is_active.is_(True)).order_by(ControlPlaneConfig.created_at)
        )
    ).scalars().first()
    if config is None and create:
        config = ControlPlaneConfig(name="default", is_active=True)
        db.add(config)
        await db.flush()
    return config


async def order_targets(db: AsyncSession) -> list[ControlPlaneRuntimeTarget]:
    """The active targets of the active configuration, in order."""
    config = await active_config(db)
    if config is None:
        return []
    return list(
        (
            await db.execute(
                select(ControlPlaneRuntimeTarget)
                .where(ControlPlaneRuntimeTarget.config_id == config.id, ControlPlaneRuntimeTarget.is_active.is_(True))
                .order_by(ControlPlaneRuntimeTarget.priority, ControlPlaneRuntimeTarget.created_at)
            )
        ).scalars().all()
    )


async def order_models(db: AsyncSession) -> list[tuple[ControlPlaneRuntimeTarget, LLMProvider, LLMModel | None]]:
    """Each order entry with its provider and catalog row (``None`` when the target names no catalog model)."""
    entries = []
    seen: set[tuple[str, str]] = set()
    for target in await order_targets(db):
        ref = (target.provider_id, target.model_id)
        if ref in seen:
            continue
        seen.add(ref)
        provider = await db.get(LLMProvider, target.provider_id)
        if provider is None:
            continue
        model = (
            await db.execute(
                select(LLMModel).where(LLMModel.provider_id == target.provider_id, LLMModel.model_id == target.model_id)
            )
        ).scalars().first()
        entries.append((target, provider, model))
    return entries


async def load_fallback_choice(db: AsyncSession) -> str:
    return fallback_choice(await get_system_config_value(db, AGENT_RUNTIME_FALLBACK_MODE_KEY))


def _keys(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_ORDER:
        raise ModelOrderError(ERROR_ORDER_INVALID)
    keys = [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]
    if len(keys) != len(value) or len(set(keys)) != len(keys):
        raise ModelOrderError(ERROR_ORDER_INVALID)
    if not keys:
        raise ModelOrderError(ERROR_ORDER_EMPTY)
    return keys


async def save_order(db: AsyncSession, *, model_keys: Any, fallback: Any, actor_id: str) -> dict[str, Any]:
    """Save the order and the fallback mode together (the page's one save); returns before/after for the audit."""
    keys = _keys(model_keys)
    if fallback not in FALLBACK_CHOICES:
        raise ModelOrderError(ERROR_FALLBACK_INVALID)
    rows = {
        model.catalog_key: model
        for model in (await db.execute(select(LLMModel).where(LLMModel.catalog_key.in_(keys)))).scalars().all()
    }
    for key in keys:
        if key not in rows:
            raise ModelOrderError(ERROR_ORDER_UNKNOWN_MODEL)
        if not rows[key].is_active:
            raise ModelOrderError(ERROR_ORDER_MODEL_OFF)
    before = [model.catalog_key for _target, _provider, model in await order_models(db) if model is not None]
    before_fallback = await load_fallback_choice(db)

    config = await active_config(db, create=True)
    targets = (
        await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.config_id == config.id))
    ).scalars().all()
    by_ref = {}
    for target in sorted(targets, key=lambda item: (item.priority or 0, str(item.created_at or ""))):
        by_ref.setdefault((target.provider_id, target.model_id), target)
    wanted = set()
    for position, key in enumerate(keys, start=1):
        model = rows[key]
        ref = (model.provider_id, model.model_id)
        wanted.add(ref)
        target = by_ref.get(ref)
        if target is None:
            target = ControlPlaneRuntimeTarget(
                config_id=config.id, provider_id=model.provider_id, model_id=model.model_id
            )
            db.add(target)
            by_ref[ref] = target
        target.priority, target.is_active = position, True
    for target in targets:
        ref = (target.provider_id, target.model_id)
        if ref not in wanted or by_ref.get(ref) is not target:
            target.is_active = False
    await set_system_config_value(
        db, key=AGENT_RUNTIME_FALLBACK_MODE_KEY, value=_STORED_MODE[fallback], updated_by=actor_id,
        description="What happens when a model fails: next allowed model (all_runtimes) or stop (first_runtime_only).",
    )
    await db.flush()
    return {"before": {"order": before, "fallback": before_fallback}, "after": {"order": keys, "fallback": fallback}}


__all__ = [
    "FALLBACK_CHOICES",
    "FALLBACK_NEXT",
    "FALLBACK_STOP",
    "ModelOrderError",
    "active_config",
    "fallback_choice",
    "load_fallback_choice",
    "order_models",
    "order_targets",
    "save_order",
]
