"""Which platform user owns the chat session of a Teams call.

Resolved exactly like a channel chat message (``channel_router_runtime/run_as.py``):

* a caller linked to a platform user through the channel's ``sender_mappings`` (keyed by the
  caller's Entra object id as Graph reports it) owns the session;
* an unresolved caller on a channel with ``require_registered_user`` is refused
  (``channel_sender_unresolved``);
* any other unresolved caller's session belongs to the channel's service user
  (``channel-service-<channel id>``, a read-only ``viewer``);
* without a valid service user the call is refused with
  ``channel_service_user_not_configured``.

A channel whose plugin is not running in this process cannot say which callers are mapped and
is refused with ``call_channel_not_active``. There is no other fallback: never the first user in
the table, never an admin.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..channel_router_runtime.run_as import ChannelRunAs, resolve_run_as_user
from ..channel_router_runtime.sender_identity import resolve_sender_user_id

STATE_CALL_CHANNEL_NOT_ACTIVE = "call_channel_not_active"


async def resolve_call_owner(
    db: AsyncSession, *, channel_id: str, project_id: str | None, caller_id: str | None
) -> ChannelRunAs:
    """The owner of the call's session, or the refusal ``state``."""
    from ...plugins import plugin_manager

    plugin = plugin_manager.get_channel(str(channel_id))
    if plugin is None or str(getattr(plugin, "plugin_id", "")) != "msteams":
        return ChannelRunAs(None, STATE_CALL_CHANNEL_NOT_ACTIVE)
    resolved = await resolve_sender_user_id(db, plugin, caller_id) if caller_id else None
    return await resolve_run_as_user(db, plugin, channel_id=str(channel_id), project_id=project_id, resolved=resolved)


__all__ = ["STATE_CALL_CHANNEL_NOT_ACTIVE", "resolve_call_owner"]
