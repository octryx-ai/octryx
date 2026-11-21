"""A test run of a CallAgent and the tools one configuration enables (admin panel).

Included into the ``/api/v1/call-agents`` router by ``call_agent.py``; this router has no prefix of its own,
so that router's admin-only dependency applies here too.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import CallAgentConfig
from ...services.access_control import require_existing_workspace
from ...services.call_agent import CallAgentService, discover_all_tools, get_call_agent_config

router = APIRouter()


# --- Test/Execute ---

@router.post("/run")
async def run_call_agent(
    project_id: str,
    user_message: str,
    transcript_context: str = "",
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Execute CallAgent for a test message.
    Used by admin UI to test the agent configuration.

    Note: This is a test endpoint, not the actual Teams Calling integration.
    Teams Calling uses CallAgentService directly in teams_calling.py.
    """
    await require_existing_workspace(db, project_id)
    config = await get_call_agent_config(db, project_id)
    if not config:
        raise HTTPException(status_code=404, detail="No CallAgent config found for this project")

    service = CallAgentService(db, config)
    result = await service.run(user_message, transcript_context)

    return {
        "user_message": user_message,
        "thinking_message": result.thinking_message,
        "final_response": result.final_response,
        "follow_up_question": result.follow_up_question,
        "tool_calls_made": result.tool_calls_made,
        "tools_used": result.tools_used,
        "error": result.error,
    }


# --- Admin Panel: enabled tools for a config ---

@router.get("/config/{config_id}/tools")
async def get_config_tools(
    config_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the enabled tools for a CallAgent config."""
    config = await db.get(CallAgentConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="CallAgent config not found")

    enabled_tools = set(config.enabled_tools or [])
    all_tools = discover_all_tools()

    # Categorize tools
    result = {}
    for category, tools in all_tools.items():
        enabled_in_category = []
        disabled_in_category = []
        for tool in tools:
            if tool["name"] in enabled_tools:
                enabled_in_category.append(tool)
            else:
                disabled_in_category.append(tool)

        result[category] = {
            "enabled": enabled_in_category,
            "disabled": disabled_in_category,
            "enabled_count": len(enabled_in_category),
            "disabled_count": len(disabled_in_category),
        }

    return {
        "config_id": config_id,
        "total_enabled": len(enabled_tools),
        "categories": result,
    }
