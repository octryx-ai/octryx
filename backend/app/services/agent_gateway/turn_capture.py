"""Turn-end memory capture for governed client sessions.

The platform captures memories at the end of a finished chat turn
(``knowledge/memory/auto_capture.run_turn_memory_capture``), off unless the
Workspace enables it. A governed client's turn ends at Claude Code's ``Stop`` when
the verification gate lets it end; a ``SubagentStop`` or a blocked ``Stop`` (the
agent is sent back to work) is not a finished turn.

The capture itself runs after the hook response (it makes a bounded model call);
this module decides, with a fixed state, whether it is scheduled. It never raises.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from ..knowledge.memory.settings import automatic_capture_enabled
from .verification import STATE_BLOCKED

HOOK_STOP = "Stop"

CAPTURE_SCHEDULED = "scheduled"
CAPTURE_DISABLED = "disabled"
CAPTURE_NOT_APPLICABLE = "not_applicable"
CAPTURE_TURN_CONTINUES = "turn_continues"
CAPTURE_FAILED = "failed"


async def turn_capture_state(
    db: AsyncSession,
    *,
    session: Session,
    hook_event: str,
    verification_state: str,
) -> str:
    """Whether the finished turn's memory capture should run, as one fixed state."""

    if hook_event != HOOK_STOP:
        return CAPTURE_NOT_APPLICABLE
    if verification_state == STATE_BLOCKED:
        return CAPTURE_TURN_CONTINUES
    try:
        enabled = await automatic_capture_enabled(db, session.project_id)
    except Exception:  # noqa: BLE001 - capture must never fail the verification response
        return CAPTURE_FAILED
    return CAPTURE_SCHEDULED if enabled else CAPTURE_DISABLED


__all__ = [
    "CAPTURE_DISABLED",
    "CAPTURE_FAILED",
    "CAPTURE_NOT_APPLICABLE",
    "CAPTURE_SCHEDULED",
    "CAPTURE_TURN_CONTINUES",
    "HOOK_STOP",
    "turn_capture_state",
]
