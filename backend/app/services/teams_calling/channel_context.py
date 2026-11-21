"""Channel configuration loading and validation for Teams calling.

Resolves per-channel calling settings (wake word policy, thinking message,
raw calling config) and validates that a channel is allowed to accept
Teams call audio connections.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ChannelConfig
from .wake_word import WakeWordPolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelCallingContext:
    """Validated Teams calling configuration for a channel."""

    channel_id: str
    project_id: str
    config: dict[str, Any]


async def get_wake_word_policy_for_channel(channel_id: str, db: AsyncSession) -> WakeWordPolicy:
    """Load wake word policy from the channel's calling config."""
    if not channel_id:
        return WakeWordPolicy()
    try:
        channel_pk = int(channel_id)
        result = await db.execute(select(ChannelConfig).where(ChannelConfig.id == channel_pk))
        channel = result.scalar_one_or_none()
        if channel:
            raw = channel.config or "{}"
            config = json.loads(raw) if isinstance(raw, str) else (raw or {})
            return WakeWordPolicy.from_config(config)
    except (ValueError, Exception):
        pass
    return WakeWordPolicy()


async def get_thinking_message(channel_id: str, db: AsyncSession) -> str:
    """Load the configured thinking message from channel config."""
    if not channel_id:
        return "One moment please."
    try:
        channel_pk = int(channel_id)
        result = await db.execute(select(ChannelConfig).where(ChannelConfig.id == channel_pk))
        channel = result.scalar_one_or_none()
        if channel:
            raw = channel.config or "{}"
            config = json.loads(raw) if isinstance(raw, str) else (raw or {})
            return str(config.get("call_agent_thinking_message") or "One moment please.")
    except Exception:
        pass
    return "One moment please."


async def get_channel_calling_config(
    db: AsyncSession,
    channel_id: str,
) -> dict[str, Any]:
    """Load calling config for a channel from the database."""
    context = await get_channel_calling_context(db, channel_id=channel_id)
    return context.config


async def get_channel_calling_context(
    db: AsyncSession,
    *,
    channel_id: str,
    project_id: str | None = None,
) -> ChannelCallingContext:
    """Load and validate the Teams calling context for an audio connection."""
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required")
    try:
        channel_pk = int(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="channel_id must be an integer") from exc

    result = await db.execute(select(ChannelConfig).where(ChannelConfig.id == channel_pk))
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    if channel.plugin_id != "msteams":
        raise HTTPException(status_code=400, detail="Channel is not a Microsoft Teams channel")
    if not channel.enabled:
        raise HTTPException(status_code=403, detail="Channel is disabled")
    if project_id and channel.project_id and str(channel.project_id) != str(project_id):
        raise HTTPException(status_code=403, detail="Channel project mismatch")

    raw = channel.config or "{}"
    config = json.loads(raw) if isinstance(raw, str) else (raw or {})
    if not config.get("calling_enabled", False):
        raise HTTPException(status_code=403, detail="Calling not enabled for this channel")

    resolved_project_id = str(channel.project_id or project_id or "")
    if not resolved_project_id:
        raise HTTPException(status_code=400, detail="Calling channel has no project binding")

    return ChannelCallingContext(
        channel_id=str(channel.id),
        project_id=resolved_project_id,
        config=config,
    )
