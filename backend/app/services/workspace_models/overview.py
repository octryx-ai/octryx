"""Global › Models: one read over every provider,
every model a workspace can choose, and what the workspaces made of it. The global level defines; a workspace only
narrows (``store.save_models``), so this view says per model in how many workspaces it is allowed, where it was
switched off and where it is the default.

Read only; the edits stay where they are (Providers, Catalog, each workspace's Models).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider, Project
from ...models.runtime.control_plane import ControlPlaneRuntimeTarget
from ..system_config.values import get_agent_default_model
from .contract import model_catalog
from .store import read_models


def _host(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).hostname or url


def provider_state(provider: LLMProvider) -> str:
    """``off`` (switched off), ``failing`` (last health check failed), else ``connected``."""
    if not provider.is_active:
        return "off"
    if str(provider.health_status or "").lower() in {"error", "failing", "unhealthy", "down"}:
        return "failing"
    return "connected"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def models_overview(db: AsyncSession) -> dict[str, Any]:
    providers = list((await db.execute(select(LLMProvider).order_by(LLMProvider.created_at))).scalars())
    llm_rows = list((await db.execute(select(LLMModel))).scalars())
    targets = {row.id: row for row in (await db.execute(select(ControlPlaneRuntimeTarget))).scalars()}
    workspaces = list((await db.execute(
        select(Project).where(Project.is_active.is_(True)).order_by(Project.name))).scalars())

    providers_by_id = {provider.id: provider for provider in providers}
    provider_rows = []
    for provider in providers:
        own = [row for row in llm_rows if row.provider_id == provider.id]
        synced = [row.last_synced_at for row in own if row.last_synced_at is not None]
        provider_rows.append({
            "id": provider.id,
            "name": provider.display_name or provider.name,
            "driver": provider.driver or provider.provider_family or provider.name,
            "endpoint": _host(provider.endpoint_url) or provider.aws_region,
            "state": provider_state(provider),
            "error": provider.last_health_error if provider_state(provider) == "failing" else None,
            "models_found": len(own),
            "models_on": sum(1 for row in own if row.is_active),
            "loaded_at": _iso(max(synced)) if synced else None,
        })

    # Per model: the LLM row behind a runtime target (price), else the gateway alias by model id.
    by_origin = {(row.provider_id, row.model_id): row for row in llm_rows}
    by_model_id: dict[str, LLMModel] = {}
    for row in llm_rows:
        by_model_id.setdefault(row.model_id, row)

    catalog = await model_catalog(db)
    usage: dict[str, dict[str, Any]] = {entry.key: {"allowed": 0, "off_in": [], "default_in": []} for entry in catalog}
    for workspace in workspaces:
        view = await read_models(db, workspace.id)
        default = view["contract"].get("default")
        for row in view["models"]:
            entry = usage.get(row["key"])
            if entry is None:
                continue
            if row["allowed"]:
                entry["allowed"] += 1
            elif row["cleared"]:
                entry["off_in"].append(workspace.name)
            if row["key"] == default:
                entry["default_in"].append(workspace.name)

    platform_default = await get_agent_default_model(db)
    model_rows = []
    for entry in catalog:
        target = targets.get(entry.target_id) if entry.target_id else None
        llm = by_origin.get((target.provider_id, target.model_id)) if target else by_model_id.get(entry.alias or "")
        model_id = target.model_id if target else entry.alias
        provider = providers_by_id.get(target.provider_id) if target else None
        model_rows.append({
            "key": entry.key,
            # A model of a switched-off provider is not offered, whatever the workspaces allowed.
            "provider_off": provider is not None and provider_state(provider) == "off",
            "label": entry.label,
            "provider": entry.provider,
            "price_in": llm.pricing_input if llm else None,
            "price_out": llm.pricing_output if llm else None,
            "cost_source": llm.cost_source if llm else None,
            "available_in": usage[entry.key]["allowed"],
            "off_in": usage[entry.key]["off_in"],
            "default_in": usage[entry.key]["default_in"],
            "platform_default": bool(model_id) and model_id == platform_default,
        })

    return {
        "providers": provider_rows,
        "models": model_rows,
        "workspaces": len(workspaces),
        "platform_default": next((row["label"] for row in model_rows if row["platform_default"]), platform_default),
    }


__all__ = ["models_overview", "provider_state"]
