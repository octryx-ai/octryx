"""Which platform user owns the chat session of a Teams call."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..channel_router_runtime.run_as import ChannelRunAs, resolve_run_as_user
from ..channel_router_runtime.sender_identity import resolve_sender_user_id

STATE_CALL_CHANNEL_NOT_ACTIVE = "call_channel_not_active"


async def resolve_call_owner(
    db: AsyncSession, *, channel_id: str, project_id: str | None, caller_id: str | None
) -> ChannelRunAs:
    from ...plugins import plugin_manager

    plugin = plugin_manager.get_channel(str(channel_id))
    if plugin is None or str(getattr(plugin, "plugin_id", "")) != "msteams":
        return ChannelRunAs(None, STATE_CALL_CHANNEL_NOT_ACTIVE)
    resolved = await resolve_sender_user_id(db, plugin, caller_id) if caller_id else None
    return await resolve_run_as_user(db, plugin, channel_id=str(channel_id), project_id=project_id, resolved=resolved)


__all__ = ["STATE_CALL_CHANNEL_NOT_ACTIVE", "resolve_call_owner"]
