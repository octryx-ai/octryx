"""Claude Code compacts a long session itself; the run only sets the window and records each compaction.

Never rebuild what Claude Code does itself: Claude Code compacts headless too, at the window
``CLAUDE_CODE_AUTO_COMPACT_WINDOW`` names; the offer carries the class's cap as that window (:func:`window`) and a
Claude Code session keeps going. Ending the session past the cap and starting a fresh one with a handoff note
(``context_cap``) is only for an engine without auto-compaction. Each compaction is a run event (``session_compacted``:
when, the trigger, the context before it and the summary's length), so the token profile shows what it cost and saved.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..records import record_event

EVENT = "session_compacted"
TRIGGERS = frozenset({"auto", "manual"})
STAGES = frozenset({"pre", "post"})


def window(run: WorkflowRun | None) -> int | None:
    """The class's cap as the window Claude Code compacts at (Claude Code's own minimum is 100000)."""
    from ..size_class import class_config

    cap = class_config(run).get("context_cap_tokens")
    return max(int(cap), 100_000) if type(cap) is int and cap > 0 else None


async def compacts_itself(db: AsyncSession, resume_session: str) -> bool:
    """The session to resume belongs to Claude Code, which compacts it at the window instead of a fresh start."""
    from ...agent_gateway.engine_keys import ENGINE_CLAUDE_CODE
    from ...devices.job_engine import _engine_of_session

    return bool(resume_session) and (await _engine_of_session(db, resume_session) or ENGINE_CLAUDE_CODE) == (
        ENGINE_CLAUDE_CODE)


async def record(db: AsyncSession, run: WorkflowRun, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """The launcher's PreCompact / PostCompact report as the run's event."""
    from .context_cap import last_context_tokens

    stage = str(body.get("stage") or "")
    if stage not in STAGES:
        return {"state": "refused", "reason": "stage is pre or post"}
    trigger = str(body.get("trigger") or "")
    summary = body.get("summary_chars")
    detail = {"stage": stage, "trigger": trigger if trigger in TRIGGERS else "unknown", "session_id": session_id,
              "context_tokens": await last_context_tokens(db, run.id),
              **({"summary_chars": summary} if type(summary) is int and summary >= 0 else {})}
    record_event(db, run, EVENT, node_id=run.current_node_id, detail=detail)
    return {"state": "recorded"}


__all__ = ["EVENT", "compacts_itself", "record", "window"]
