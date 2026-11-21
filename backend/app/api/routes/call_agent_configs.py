"""CallAgent configurations: read, list, create, update and delete.

Included into the ``/api/v1/call-agents`` router by ``call_agent.py``; this router has no prefix of its own,
so that router's admin-only dependency applies here too.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import CallAgentConfig, Project
from ...services.access_control import require_existing_workspace
from ...services.call_agent import create_call_agent, get_call_agent_config
from ...services.error_facts import error_text, error_type

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Config CRUD ---

@router.get("/config")
async def get_config(
    project_id: str = Query(..., description="Project ID"),
    channel_id: str | None = Query(None, description="Optional channel ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get CallAgentConfig for a project/channel."""
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    config = await get_call_agent_config(db, project_id, channel_id)

    if not config:
        raise HTTPException(status_code=404, detail="No CallAgent config found for this project")

    return config.to_dict()


@router.get("/configs")
async def list_configs(
    project_id: str = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all CallAgent configs for a project."""
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(CallAgentConfig)
        .where(CallAgentConfig.project_id == project_id)
        .order_by(CallAgentConfig.name)
    )
    configs = list(result.scalars().all())
    serialized = []
    for c in configs:
        try:
            serialized.append(c.to_dict())
        except Exception as exc:
            logger.exception("to_dict() failed for config %s (%s)", c.id, error_type(exc))
            raise HTTPException(
                status_code=500,
                detail=f"Failed to serialize config. {error_text('call_agent_config_serialize_failed', exc)}",
            ) from exc

    return {
        "configs": serialized,
        "count": len(configs),
    }


@router.post("/config")
async def create_config(
    project_id: str = Query(...),
    name: str = Query(...),
    enabled_tools: list[str] | None = Query(None),
    system_prompt: str | None = Query(None),
    llm_model: str = Query("claude-sonnet-4-4"),
    max_tool_calls: int = Query(5, ge=1, le=20),
    thinking_message: str = Query("One moment please, I'm looking into this."),
    channel_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new CallAgentConfig."""
    await require_existing_workspace(db, project_id)

    # Check for duplicate name within project
    existing = await db.execute(
        select(CallAgentConfig).where(
            CallAgentConfig.project_id == project_id,
            CallAgentConfig.name == name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="CallAgent with this name already exists in project")

    config = await create_call_agent(
        db=db,
        project_id=project_id,
        name=name,
        enabled_tools=enabled_tools or [],
        system_prompt=system_prompt,
        llm_model=llm_model,
        max_tool_calls=max_tool_calls,
        thinking_message=thinking_message,
    )

    if channel_id:
        config.channel_id = channel_id
        await db.commit()

    return config.to_dict()


@router.patch("/config/{config_id}")
async def update_config(
    config_id: str,
    updates: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a CallAgentConfig."""
    config = await db.get(CallAgentConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="CallAgent config not found")

    # Allowed fields to update
    allowed_fields = {
        "name",
        "llm_model",
        "max_tool_calls",
        "system_prompt",
        "enabled_tools",
        "thinking_message",
        "is_active",
        "channel_id",
    }

    for key, value in updates.items():
        if key in allowed_fields:
            setattr(config, key, value)

    await db.commit()
    await db.refresh(config)

    return config.to_dict()


@router.delete("/config/{config_id}")
async def delete_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Soft-delete a CallAgentConfig (set is_active=False)."""
    config = await db.get(CallAgentConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="CallAgent config not found")

    config.is_active = False
    await db.commit()

    return {"status": "deleted", "id": config_id}
