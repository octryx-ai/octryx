"""Which platform user a channel sender is.

A sender resolves to a platform user only through an explicit link: the plugin's
``sender_mappings`` (sender id -> active user id) or, for the email channel, the sender's
address matching an active user's email. :func:`resolve_sender_user_id` returns ``None`` for
anyone else. Whatever a channel does for an unresolved sender elsewhere, a decision such as an
approval is never taken for one (``approval_commands.py``: ``channel_sender_unresolved``).
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select

from ...models.security.user import User

logger = logging.getLogger(__name__)

STATE_SENDER_UNRESOLVED = "channel_sender_unresolved"
_EMAIL_IN_BRACKETS = re.compile(r"<([^>]+)>")


async def resolve_sender_user_id(db, plugin, sender_id: str) -> str | None:
    """The active platform user linked to ``sender_id``, else ``None``."""
    mappings = getattr(plugin, "sender_mappings", None) or {}
    mapped_user_id = mappings.get(sender_id) if isinstance(mappings, dict) else None
    if mapped_user_id:
        user = (await db.execute(select(User).where(User.id == mapped_user_id, User.is_active))).scalar_one_or_none()
        if user is not None:
            return user.id
    if str(getattr(plugin, "plugin_id", "") or "") == "email" and "@" in sender_id:
        match = _EMAIL_IN_BRACKETS.search(sender_id)
        email = match.group(1) if match else sender_id.strip()
        user = (await db.execute(select(User).where(User.email == email, User.is_active))).scalar_one_or_none()
        if user is not None:
            logger.debug("Resolved an email sender to a platform user")
            return user.id
    return None


__all__ = ["STATE_SENDER_UNRESOLVED", "resolve_sender_user_id"]
