"""The Default & fallback page payload: platform order, fallback choice, task models and the enabled models.

Models are shown by display name; the catalog key is the only identifier the page sends back.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider
from ..model_catalog.contract import capabilities_of
from ..model_catalog.views import provider_label
from .platform_order import load_fallback_choice, order_models
from .task_models import TASKS, load_task_models, workspace_override_counts


def model_summary(provider: LLMProvider, model: LLMModel) -> dict[str, Any]:
    return {
        "catalog_key": model.catalog_key,
        "display_name": model.display_name or model.model_id,
        "provider": provider_label(provider),
        "enabled": bool(model.is_active),
        "provider_active": bool(provider.is_active),
        "cleared_up_to": model.cleared_up_to,
        "capabilities": capabilities_of(model),
    }


async def enabled_models(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(LLMProvider, LLMModel)
            .join(LLMModel, LLMModel.provider_id == LLMProvider.id)
            .where(LLMModel.is_active.is_(True))
            .order_by(LLMModel.display_name, LLMModel.model_id)
        )
    ).all()
    return [model_summary(provider, model) for provider, model in rows]


async def default_and_fallback_page(db: AsyncSession) -> dict[str, Any]:
    order = []
    for _target, provider, model in await order_models(db):
        if model is None:
            continue  # a target without a catalog row cannot be named
        order.append(model_summary(provider, model))
    task_models = await load_task_models(db)
    counts = await workspace_override_counts(db)
    return {
        "order": order,
        "fallback": await load_fallback_choice(db),
        "tasks": [
            {"key": key, "label": label, "model_key": task_models.get(key), "workspace_overrides": counts.get(key, 0)}
            for key, label in TASKS
        ],
        "models": await enabled_models(db),
    }


__all__ = ["default_and_fallback_page", "enabled_models", "model_summary"]
