"""Explicit agent-mode requirement for Agent Definition writes."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .normalization import normalize_agent_mode_key
from .service import ResolvedAgentMode, resolve_agent_mode

#: Typed code shared with the validator's ``unknown_agent_type`` issue.
UNKNOWN_AGENT_MODE_CODE = "unknown_agent_mode"
UNKNOWN_AGENT_MODE_MESSAGE = (
    "The requested agent mode is not an active, publishable agent mode; "
    "configure the mode or choose an active one."
)

#: Echoed keys are bounded as well as narrow-charset, so an oversized value cannot be
#: reflected back through an error payload.
MAX_ECHOED_MODE_KEY_LENGTH = 64


class UnknownAgentModeError(HTTPException):
    """422 for an explicitly requested agent mode that cannot be published."""

    def __init__(self, mode_key: str, *, field: str = "agent_type") -> None:
        self.mode_key = mode_key
        self.field = field
        super().__init__(
            status_code=422,
            detail={
                "message": UNKNOWN_AGENT_MODE_MESSAGE,
                "code": UNKNOWN_AGENT_MODE_CODE,
                "field": field,
                "subject": mode_key[:MAX_ECHOED_MODE_KEY_LENGTH],
            },
        )


async def require_agent_mode(
    db: AsyncSession, mode_key: str | None, *, field: str = "agent_type"
) -> ResolvedAgentMode:
    """Resolve *mode_key* or fail closed."""
    from ..agent_definition_validation import publishable_agent_type_keys

    requested = str(mode_key or "").strip()
    if not requested:
        return await resolve_agent_mode(db, None)
    normalized = normalize_agent_mode_key(requested)
    # The key set is authoritative before any seeding: it accepts a code-backed system
    # mode that this database has not stored yet, exactly as publication does.
    if normalized not in await publishable_agent_type_keys(db):
        raise UnknownAgentModeError(normalized, field=field)
    return await resolve_agent_mode(db, normalized)


__all__ = [
    "MAX_ECHOED_MODE_KEY_LENGTH",
    "UNKNOWN_AGENT_MODE_CODE",
    "UNKNOWN_AGENT_MODE_MESSAGE",
    "UnknownAgentModeError",
    "require_agent_mode",
]
