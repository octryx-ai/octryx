"""CallAgent configuration rows: lookup by project/channel and creation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CallAgentConfig as CallAgentConfigModel


async def get_call_agent_config(
    db: AsyncSession,
    project_id: str,
    channel_id: str | None = None,
) -> CallAgentConfigModel | None:
    """
    Get CallAgentConfig for a project/channel.

    If channel_id is provided, looks for channel-specific config first,
    then falls back to project-level config.
    """
    # Try channel-specific first
    if channel_id:
        result = await db.execute(
            select(CallAgentConfigModel).where(
                CallAgentConfigModel.project_id == project_id,
                CallAgentConfigModel.channel_id == channel_id,
                CallAgentConfigModel.is_active.is_(True),
            )
        )
        config = result.scalar_one_or_none()
        if config:
            return config

    # Fall back to project-level (no channel filter)
    result = await db.execute(
        select(CallAgentConfigModel).where(
            CallAgentConfigModel.project_id == project_id,
            CallAgentConfigModel.channel_id.is_(None),
            CallAgentConfigModel.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def create_call_agent(
    db: AsyncSession,
    project_id: str,
    name: str,
    enabled_tools: list[str] | None = None,
    system_prompt: str | None = None,
    llm_model: str = "claude-sonnet-4-4",
    max_tool_calls: int = 5,
    thinking_message: str = "One moment please, I'm looking into this.",
) -> CallAgentConfigModel:
    """Create a new CallAgentConfig."""
    import uuid

    config = CallAgentConfigModel(
        id=str(uuid.uuid4()),
        name=name,
        project_id=project_id,
        enabled_tools=enabled_tools or [],
        system_prompt=system_prompt,
        llm_model=llm_model,
        max_tool_calls=max_tool_calls,
        thinking_message=thinking_message,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config
