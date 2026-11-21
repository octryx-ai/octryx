"""API routes for CallAgent configuration and management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.auth.admin_principal import get_current_admin_user
from ...services.call_agent import discover_all_tools, discover_configured_tools
from .call_agent_configs import router as configs_router
from .call_agent_execution import router as execution_router

# Admin-only: a calling agent's model, prompt and tools are platform configuration, and a run
# executes it with tools; the admin panel tab is the only caller.
router = APIRouter(
    prefix="/api/v1/call-agents", tags=["call-agents"], dependencies=[Depends(get_current_admin_user)]
)


# --- Tool Discovery ---

@router.get("/tools/available")
async def get_available_tools() -> dict[str, Any]:
    """
    Return all available tools, grouped by connector/category.

    This endpoint doesn't require auth — used by admin UI to populate
    the tool selection form.
    """
    tools = discover_all_tools()

    # Sort by category name
    sorted_tools = dict(sorted(tools.items()))

    return {
        "tools": sorted_tools,
        "total_count": sum(len(v) for v in sorted_tools.values()),
        "categories": list(sorted_tools.keys()),
    }


@router.get("/tools/configured")
async def get_configured_tools(
    project_id: str = Query(..., description="Project ID"),
    channel_id: str | None = Query(None, description="Optional channel ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return only the tools configured for this project/channel.

    That means: connector tools of channels activated in the project, plus the
    internal system tools (knowledge, memory, ...).
    """
    tools = await discover_configured_tools(db, project_id=project_id, channel_id=channel_id)

    sorted_tools = dict(sorted(tools.items()))

    return {
        "tools": sorted_tools,
        "total_count": sum(len(v) for v in sorted_tools.values()),
        "categories": list(sorted_tools.keys()),
    }


@router.get("/runtimes/models")
async def get_runtime_models(
    project_id: str = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return the available LLM models based on the configured runtimes.

    Loads the providers/runtimes activated for this project and extracts the
    available models.
    """
    from ...models import LLMModel, LLMProvider

    result = await db.execute(
        select(LLMProvider).where(
            LLMProvider.is_active.is_(True),
            (LLMProvider.project_id == project_id) | (LLMProvider.project_id.is_(None)),
        )
    )
    providers = list(result.scalars().all())

    models = []
    for provider in providers:
        # Get active models for this provider
        model_result = await db.execute(
            select(LLMModel).where(
                LLMModel.provider_id == provider.id,
                LLMModel.is_active.is_(True),
            )
        )
        provider_models = list(model_result.scalars().all())

        for model in provider_models:
            models.append({
                "id": model.id,
                "name": model.model_id,
                "display_name": model.display_name or model.model_id,
                "provider_id": provider.id,
                "provider_name": provider.display_name or provider.name,
                "context_length": model.context_length,
            })

    return {
        "models": models,
        "count": len(models),
    }


# Included after the routes above so the registration order stays the same.
router.include_router(configs_router)
router.include_router(execution_router)
