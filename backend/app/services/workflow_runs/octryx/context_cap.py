"""A session whose last call read more than the class's ``context_cap_tokens`` is not resumed: the pass starts fresh
with a handoff note, and the branch carries the work (``size_classes``).

Resuming the session is the default up to the workflow's cap; past the cap the next pass starts fresh with a
handoff and reads only what it needs.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import UsageEvent, WorkflowRun, WorkflowRunSession
from ..records import record_event

EVENT_CAPPED = "session_context_capped"
CAPPED_KEY = "session_context_capped_pass"
#: The handoff note of a fresh pass after the cap is the catalog text ``run.context_cap.handoff``.


async def last_context_tokens(db: AsyncSession, run_id: str) -> int:
    """The context of the run's last device-agent model call (its sessions' newest gateway usage)."""
    sessions = select(WorkflowRunSession.session_id).where(WorkflowRunSession.run_id == run_id)
    row = (await db.execute(
        select(UsageEvent.tokens_in, UsageEvent.cache_read_tokens, UsageEvent.cache_creation_tokens)
        .where(UsageEvent.session_id.in_(sessions), UsageEvent.dispatch_owner.like("model_gateway_inbound%"))
        .order_by(UsageEvent.created_at.desc()).limit(1))).first()
    return sum(int(value or 0) for value in row) if row is not None else 0


def source_run_id(run: WorkflowRun, *, epic: bool) -> str:
    """The run whose session a pass resumes: the epic's previous story for an epic resume, else the run itself."""
    from ..epic_chain import CHAIN_KEY

    previous = str(dict(dict(run.context or {}).get(CHAIN_KEY) or {}).get("after_run") or "")
    return previous if epic and previous else run.id


async def over_cap(db: AsyncSession, run: WorkflowRun, *, source_run_id: str, node_id: str) -> bool:
    """``True`` (and the event, once per pass) when the run's class caps the session it would resume."""
    from ..size_class import class_config

    cap = class_config(run).get("context_cap_tokens")
    if type(cap) is not int:
        return False
    this_pass = f"{node_id}:{dict(run.node_state or {}).get('entry')}"
    if dict(run.context or {}).get(CAPPED_KEY) == this_pass:
        return True  # the same pass starting again (another model): decided and recorded once
    tokens = await last_context_tokens(db, source_run_id)
    if tokens <= cap:
        return False
    run.context = {**dict(run.context or {}), CAPPED_KEY: this_pass}
    record_event(db, run, EVENT_CAPPED, node_id=node_id,
                 detail={"context_tokens": tokens, "cap": cap, "source_run_id": source_run_id})
    return True


__all__ = ["EVENT_CAPPED", "last_context_tokens", "over_cap", "source_run_id"]
