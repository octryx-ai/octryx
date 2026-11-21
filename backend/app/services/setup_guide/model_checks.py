"""The model checks of the setup guide, read from what a turn reads.

- **Models enabled**: at least one enabled Model catalog model cleared for some data (an uncleared model answers
  nowhere).
- **Default is ready**: #1 of the platform order is enabled, cleared, its provider can run, a gateway alias is
  admitted by its catalog, and it has a price whenever the unpriced-model guard would otherwise refuse every turn.
- **Prices** (not blocking): #1 has a price, otherwise its costs are not counted (with ``warn``, the default).
- **Gateway admitted** (only with a model gateway): the connection can run and how many aliases its catalog admits.
- **Workspaces**: how many active Workspaces have no model the resolver would let answer (allowed + cleared).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider, Project
from ..budget.model_pricing import resolve_model_pricing
from ..budget.unpriced_guard import POLICY_BLOCK, cost_cap_active, is_platform_billed_driver, unpriced_model_policy
from ..model_gateway.litellm.alias_catalog import resolve_alias_admission
from ..model_selection.gates import gate
from ..model_selection.platform_order import order_models
from ..model_selection.snapshot import load_scope, load_snapshot

GATEWAY_DRIVER = "litellm_gateway"


def step(key: str, title: str, done: bool, description: str, detail: str, *, blocking: bool, action: str,
         action_label: str) -> dict[str, Any]:
    return {
        "key": key, "title": title, "status": "completed" if done else "pending", "description": description,
        "detail": detail, "blocking": blocking, "action": action, "action_label": action_label,
    }


def _admitted(provider: LLMProvider, alias: str) -> bool:
    return bool(resolve_alias_admission(alias, provider.config_json).admitted)


async def models_step(db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(select(LLMModel).where(LLMModel.is_active.is_(True)))).scalars().all()
    cleared = [row for row in rows if row.cleared_up_to]
    return step(
        "models", "Models enabled", bool(cleared),
        "Enable at least one model in the Model catalog and clear it for data.",
        f"{len(rows)} enabled · {len(cleared)} cleared for data",
        blocking=True, action="open_model_catalog", action_label="Open the Model catalog",
    )


async def default_step(db: AsyncSession, runnable: dict[str, LLMProvider]) -> dict[str, Any]:
    entries = await order_models(db)
    if not entries:
        detail, done = "The platform order is empty.", False
    else:
        _target, provider, model = entries[0]
        name = (model.display_name if model else None) or _target.model_id
        problems = []
        if model is None or not model.is_active:
            problems.append("not enabled")
        elif not model.cleared_up_to:
            problems.append("not cleared for data")
        if provider.id not in runnable:
            problems.append("its provider cannot run")
        elif provider.driver == GATEWAY_DRIVER and not _admitted(provider, _target.model_id):
            problems.append("the gateway does not admit it")
        if model is not None and await _refused_as_unpriced(db, provider, _target.model_id):
            problems.append("it has no price while cost caps are on (set it in the Model catalog)")
        done = not problems
        detail = f"{name} is #1 and answers." if done else f"{name} is #1 but {', '.join(problems)}."
    return step(
        "default", "Default is ready", done,
        "#1 of the platform order runs when nobody chose a model.",
        detail, blocking=True, action="open_runtime_tab", action_label="Open Default & fallback",
    )


async def prices_step(db: AsyncSession) -> dict[str, Any] | None:
    """Only shown for a platform-billed #1 without a price; blocking stays with ``default`` under ``block``."""
    entries = await order_models(db)
    if not entries:
        return None
    target, provider, model = entries[0]
    if model is None or not is_platform_billed_driver(provider.driver or provider.name, provider.runtime_kind):
        return None
    if (await resolve_model_pricing(db, provider_name=provider.name, model_id=target.model_id)).priced:
        return None
    name = model.display_name or target.model_id
    return step(
        "prices", "Model prices", False,
        "Cost caps and usage costs count only models with a price.",
        f"{name} has no price – costs are not counted.",
        blocking=False, action="open_model_catalog", action_label="Open the Model catalog",
    )


async def _refused_as_unpriced(db: AsyncSession, provider: LLMProvider, model_id: str) -> bool:
    """What ``enforce_priced_models_under_cap`` would refuse for a platform-wide turn (no Workspace caps)."""
    if not is_platform_billed_driver(provider.driver or provider.name, provider.runtime_kind):
        return False
    if await unpriced_model_policy(db) != POLICY_BLOCK:
        return False
    if not await cost_cap_active(db, project_id=None, policies=[]):
        return False
    return not (await resolve_model_pricing(db, provider_name=provider.name, model_id=model_id)).priced


def gateway_step(providers: list[LLMProvider], runnable: dict[str, LLMProvider]) -> dict[str, Any] | None:
    gateways = [provider for provider in providers if provider.driver == GATEWAY_DRIVER]
    if not gateways:
        return None
    aliases = [(gateway, alias) for gateway in gateways
               for alias in (((gateway.config_json or {}).get("litellm_gateway") or {}).get("aliases") or {})]
    admitted = [pair for pair in aliases if _admitted(*pair)]
    linked = all(gateway.id in runnable for gateway in gateways)
    return step(
        "gateway", "Gateway admitted", linked and bool(admitted),
        "The model gateway connection can run and its catalog admits the aliases people use.",
        f"{'Connection ready' if linked else 'Connection not ready'}; "
        f"{len(admitted)} of {len(aliases)} aliases admitted.",
        blocking=False, action="", action_label="",
    )


async def workspaces_step(db: AsyncSession) -> dict[str, Any]:
    snapshot = await load_snapshot(db)
    projects = (await db.execute(select(Project.id).where(Project.is_active.is_(True)))).scalars().all()
    blocked = 0
    for project_id in projects:
        scope = await load_scope(db, workspace_id=project_id)
        if not any(not gate(model, scope) for model in snapshot.models.values()):
            blocked += 1
    return step(
        "workspaces", "Workspaces", blocked == 0,
        "Every Workspace needs at least one model it allows and that is cleared for its data class.",
        "Every Workspace can use a model." if blocked == 0 else
        f"{blocked} {'Workspace has' if blocked == 1 else 'Workspaces have'} no model cleared for their data class.",
        blocking=False, action="open_explain", action_label="Explain",
    )


__all__ = ["default_step", "gateway_step", "models_step", "prices_step", "step", "workspaces_step"]
