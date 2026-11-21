"""Explicit permission-mode choice for Automation targets.

Actions (tasks) and inbound webhooks store a permission-mode key as ``agent_type``.
``resolve_agent_mode`` silently substitutes a fallback for an empty or unknown key and
accepts a deactivated one, so an *explicitly submitted* value is held to the same
contract as an Agent Definition write (``require_agent_mode``): it must name an
active, publishable mode. Unlike that contract, an explicit blank is not "unset" here:
an empty Automation form must not silently become the default mode.

Callers decide what counts as explicit; an API omission keeps its existing default.
The runtime and every other caller keep ``resolve_agent_mode``.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.runtime_defaults import DEFAULT_AGENT_MODE_KEY
from .requirements import require_agent_mode
from .service import resolve_agent_mode

AGENT_MODE_REQUIRED_CODE = "agent_mode_required"
AGENT_MODE_REQUIRED_MESSAGE = "Choose an active permission mode."
INVALID_AGENT_MODE_KEY_CODE = "invalid_agent_mode_key"
INVALID_AGENT_MODE_KEY_MESSAGE = "The permission mode must be a mode key (letters, digits or _)."
_NON_KEY_CHARACTERS = re.compile(r"[^a-z0-9]+")


def authoring_key_form(value: str) -> str:
    """The key ``normalize_agent_mode_key`` derives, *without* its default fallback.

    Same rule as ``normalization.normalize_agent_mode_key`` (lower-case, runs of other characters
    become ``_``, outer ``_`` stripped). An empty result means the value names no key at all:
    punctuation, underscores or non-ASCII letters only. The global function
    maps that to the default mode; an explicit Automation choice must not.
    """
    return _NON_KEY_CHARACTERS.sub("_", value.strip().lower()).strip("_")


async def require_explicit_agent_mode(db: AsyncSession, value: Any, *, field: str = "agent_type") -> str:
    """The stored key for an explicitly submitted mode, or a typed 422 before any write.

    Blank or non-text → ``agent_mode_required``; no key characters (``"!!!"``, ``"___"``, ``"…"``) →
    ``invalid_agent_mode_key``; unknown or inactive → ``unknown_agent_mode``.
    """
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=422,
            detail={"message": AGENT_MODE_REQUIRED_MESSAGE, "code": AGENT_MODE_REQUIRED_CODE, "field": field},
        )
    if not authoring_key_form(value):
        # Refused here, before require_agent_mode can normalize it to the default mode.
        raise HTTPException(
            status_code=422,
            detail={"message": INVALID_AGENT_MODE_KEY_MESSAGE, "code": INVALID_AGENT_MODE_KEY_CODE, "field": field},
        )
    return (await require_agent_mode(db, value, field=field)).key


async def authored_agent_mode(db: AsyncSession, payload: dict[str, Any], *, field: str = "agent_type") -> str:
    """Create path: an explicit value is validated; an omitted key keeps its existing default resolution."""
    if field in payload:
        return await require_explicit_agent_mode(db, payload[field], field=field)
    return (await resolve_agent_mode(db, DEFAULT_AGENT_MODE_KEY)).key


__all__ = [
    "AGENT_MODE_REQUIRED_CODE",
    "AGENT_MODE_REQUIRED_MESSAGE",
    "INVALID_AGENT_MODE_KEY_CODE",
    "INVALID_AGENT_MODE_KEY_MESSAGE",
    "authoring_key_form",
    "authored_agent_mode",
    "require_explicit_agent_mode",
]
