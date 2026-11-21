"""Which platform user a channel message runs as.

* A sender linked to a platform user (``sender_identity.py``) runs as that user.
* An unresolved sender on a channel with ``require_registered_user`` is refused
  (``channel_sender_unresolved``), silently.
* Any other unresolved sender runs as the channel's own service user
  (``services/channel_config/service_user.py``: a ``viewer``, read-only in the channel's
  Workspace). A channel without a valid service user refuses with
  ``channel_service_user_not_configured``; there is no other fallback, never an arbitrary active
  user or an admin.
"""

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
    """``user_id`` to run as, or the refusal ``state`` (and the reply to send, if any)."""

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
