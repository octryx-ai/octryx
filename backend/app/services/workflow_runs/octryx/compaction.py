"""Claude Code compacts a long session itself; the run only sets the window and records each compaction."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..records import record_event

EVENT = "session_compacted"
TRIGGERS = frozenset({"auto", "manual"})
STAGES = frozenset({"pre", "post"})


def window(run: WorkflowRun | None) -> int | None:
    from ..size_class import class_config

    cap = class_config(run).get("context_cap_tokens")
    return max(int(cap), 100_000) if type(cap) is int and cap > 0 else None


async def compacts_itself(db: AsyncSession, resume_session: str) -> bool:
    from ...agent_gateway.engine_keys import ENGINE_CLAUDE_CODE
    from ...devices.job_engine import _engine_of_session

    return bool(resume_session) and (await _engine_of_session(db, resume_session) or ENGINE_CLAUDE_CODE) == (
        ENGINE_CLAUDE_CODE)


async def record(db: AsyncSession, run: WorkflowRun, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
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
