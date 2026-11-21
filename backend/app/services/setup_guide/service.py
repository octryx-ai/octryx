"""DB-backed setup guide for first-time platform initialization."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import LLMProvider
from ..control_plane_service import get_or_create_control_plane_config, get_runtime_targets
from ..local_bootstrap import get_local_bootstrap_status
from ..provider.readiness import resolve_provider_readiness
from .model_checks import default_step, gateway_step, models_step, prices_step, workspaces_step


def _step(
    *,
    key: str,
    title: str,
    status: str,
    description: str,
    detail: str,
    blocking: bool,
    action: str,
    action_label: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "description": description,
        "detail": detail,
        "blocking": blocking,
        "action": action,
        "action_label": action_label,
    }


def _runtime_attempt_allowed(provider: LLMProvider) -> bool:
    """The provider readiness contract the runtime selection uses (`services/provider/readiness.py`)."""

    return resolve_provider_readiness(provider).get("runtime_attempt_allowed") is True


async def get_setup_guide_status(db: AsyncSession) -> dict[str, Any]:
    bootstrap = await get_local_bootstrap_status(db)
    config = await get_or_create_control_plane_config(db)
    runtime_targets = await get_runtime_targets(db, config, active_only=False)
    active_runtime_targets = [target for target in runtime_targets if target.is_active]

    # Readiness reads credential state from the provider-owned oauth_config row, so it
    # is eager-loaded (an async lazy load would fail).
    providers = (
        (
            await db.execute(
                select(LLMProvider).options(selectinload(LLMProvider.oauth_config)).where(LLMProvider.is_active)
            )
        )
        .scalars()
        .all()
    )
    active_api_providers = [provider for provider in providers if (provider.runtime_kind or "api") == "api"]
    active_local_providers = [provider for provider in providers if (provider.runtime_kind or "") == "local"]
    # "Runnable" is the runtime selection's own contract: active, supported driver, and the
    # readiness check allows a runtime attempt (configuration complete, health not failed).
    runnable_providers = {provider.id: provider for provider in providers if _runtime_attempt_allowed(provider)}

    local_anchor_ready = bool(bootstrap.get("setup_complete"))
    provider_ready = bool(runnable_providers)
    ready_names = ", ".join(sorted(p.display_name or p.name for p in runnable_providers.values()))

    # Provider ready → models enabled + cleared → default (#1 of the order) ready → gateway admitted →
    # Workspaces can use a model. The checks read what a turn reads (model_checks.py).
    steps = [
        _step(
            key="provider",
            title="Provider ready",
            status="completed" if provider_ready else "pending",
            description="At least one provider connection can run.",
            detail=f"{ready_names} answer." if provider_ready else "No provider connection can run yet.",
            blocking=True,
            action="open_api_provider_form",
            action_label="Add provider",
        ),
    ]
    if not provider_ready:
        steps.append(
            _step(
                key="local_anchor",
                title="Local model (optional)",
                status="completed" if local_anchor_ready else "pending",
                description="Without a hosted provider, a local model lets a fresh system answer.",
                detail=f"{bootstrap.get('provider_display_name') or 'Not configured'}",
                blocking=False,
                action="configure_local_anchor",
                action_label="Set up a local model",
            )
        )
    steps += [await models_step(db), await default_step(db, runnable_providers)]
    if (prices := await prices_step(db)) is not None:
        steps.append(prices)
    gateway = gateway_step(list(providers), runnable_providers)
    if gateway is not None:
        steps.append(gateway)
    steps.append(await workspaces_step(db))

    blocking_pending = [step for step in steps if step["blocking"] and step["status"] != "completed"]
    ready = len(blocking_pending) == 0

    return {
        "ready": ready,
        "summary": (
            "Core setup is ready: a provider can run and the platform default answers."
            if ready
            else "Core setup still needs action before the platform is fully initialized."
        ),
        "stats": {
            "active_provider_count": len(providers),
            "api_provider_count": len(active_api_providers),
            "local_provider_count": len(active_local_providers),
            "active_runtime_count": len(active_runtime_targets),
        },
        "steps": steps,
    }
