"""Agent messages sent through a channel plugin carry the marker line when they reach people besides the requester."""

from __future__ import annotations

import logging
from typing import Any

from .ai_marking import MarkingFacts, with_marker
from .ai_marking_responsible import responsible_name

logger = logging.getLogger(__name__)

# One-to-one conversations per platform (Teams "personal", Slack "im", Telegram "private"); an unknown type is one too.
DIRECT_CHANNEL_TYPES = frozenset({"", "personal", "im", "private", "direct", "dm"})


def reaches_others(channel_type: str | None) -> bool:
    return str(channel_type or "").strip().lower() not in DIRECT_CHANNEL_TYPES


async def marked_message(db: Any, text: str, *, user_id: str | None, fallback_name: str = "") -> str:
    try:
        name = await responsible_name(db, user_id=user_id) or fallback_name.strip()
    except Exception:  # noqa: BLE001 - marking must never fail the send
        logger.debug("ai marking: channel responsible lookup failed", exc_info=True)
        name = fallback_name.strip()
    return with_marker(text, MarkingFacts(responsible=name)) if name else text
