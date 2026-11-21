"""Explicit agent-mode requirement for Agent Definition writes.

``resolve_agent_mode`` substitutes the configured default for an unknown key. That suits
the runtime path, where ``Session.agent_type`` also carries session-kind
markers (``external_agent``, ``teams_call``, ``review``) that were never mode keys.
It is *not* acceptable where an administrator supplies the ``agent_type`` of an Agent
Definition: silently storing a different mode than the one requested both misreports
the definition and produces rows that publication must later reject.

``require_agent_mode`` is the write-path contract. It accepts exactly the keys
publication accepts — ``publishable_agent_type_keys`` from
:mod:`app.services.agent_definition_validation` — so a definition can never be written
with a type that could not be published, and an explicitly deactivated mode is refused
here as it is there.

A blank or missing key is *unset*, not unknown, and still resolves to the configured
default; only an explicit unknown key fails. The failure is an HTTP 422 carrying a
typed code and the offending key only: the key is normalized to ``[a-z0-9_]`` and
length-bounded, so no free text, prompt content, or configuration value can leak
through it.
"""

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
    """Resolve *mode_key* or fail closed.

    Raises :class:`UnknownAgentModeError` when a non-empty key is not one of the
    publishable agent-mode keys. Returns the resolved mode otherwise, including for an
    unset key, which resolves to the configured default.
    """
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
