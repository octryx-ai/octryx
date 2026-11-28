"""Which platform user a channel message runs as."""

from __future__ import annotations

from dataclasses import dataclass

from ..channel_config.service_user import STATE_SERVICE_USER_NOT_CONFIGURED, resolve_channel_service_user_id
from .sender_identity import STATE_SENDER_UNRESOLVED

SERVICE_USER_NOT_CONFIGURED_REPLY = (
    f"{STATE_SERVICE_USER_NOT_CONFIGURED}: this channel has no service user for unregistered senders. "
    "Ask an administrator to set the channel up again."
)


@dataclass(frozen=True, slots=True)
class ChannelRunAs:
    user_id: str | None
    state: str | None = None
    reply: str | None = None


async def resolve_run_as_user(
    db, plugin, *, channel_id: str, project_id: str | None, resolved: str | None
) -> ChannelRunAs:
    if resolved:
        return ChannelRunAs(resolved)
    if getattr(plugin, "require_registered_user", False):
        return ChannelRunAs(None, STATE_SENDER_UNRESOLVED)
    service_user_id = await resolve_channel_service_user_id(db, channel_id, project_id)
    if service_user_id is None:
        return ChannelRunAs(None, STATE_SERVICE_USER_NOT_CONFIGURED, SERVICE_USER_NOT_CONFIGURED_REPLY)
    return ChannelRunAs(service_user_id)


__all__ = ["SERVICE_USER_NOT_CONFIGURED_REPLY", "ChannelRunAs", "resolve_run_as_user"]
