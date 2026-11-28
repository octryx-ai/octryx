"""One rule for turns without a live owner, applied at startup and by the sweeper."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog
from ..product_run.interruption import settle_orphaned_attempts
from ..session.turn_interruption import INTERRUPTED_BY_RESTART, settle_orphaned_running_sessions
from ..workflow_runs.restart_interruption import pause_runs_of_interrupted_sessions
from .process_lease import prune_expired_process_leases
from .task_runs import settle_orphaned_task_runs

logger = logging.getLogger(__name__)

TRIGGER_STARTUP = "startup"
TRIGGER_SWEEP = "sweep"
TRIGGERS = frozenset({TRIGGER_STARTUP, TRIGGER_SWEEP})
AUDIT_ACTION = "runtime.turn_interrupted"


@dataclass(frozen=True, slots=True)
class InterruptionSettlement:
    sessions: int
    attempts: int
    pruned_leases: int
    paused_runs: int = 0
    task_runs: int = 0


async def settle_interrupted_turns(db: AsyncSession, *, trigger: str) -> InterruptionSettlement:
    if trigger not in TRIGGERS:
        raise ValueError("unknown interruption trigger")
    sessions = await settle_orphaned_running_sessions(db)
    attempts = await settle_orphaned_attempts(db)
    # A workflow run whose Server turn was among them pauses instead of staying ``running`` with nobody driving it.
    paused_runs = await pause_runs_of_interrupted_sessions(db, sessions)
    task_runs = await settle_orphaned_task_runs(db)

    owners: dict[str, str] = {session.id: session.user_id for session in sessions}
    attempt_counts: Counter[str] = Counter()
    for attempt in attempts:
        owners.setdefault(attempt.session_id, attempt.owner_user_id)
        attempt_counts[attempt.session_id] += 1
    settled_session_ids = {session.id for session in sessions}
    for session_id, user_id in owners.items():
        db.add(
            AuditLog(
                user_id=user_id,
                session_id=session_id,
                action=AUDIT_ACTION,
                resource_type="session",
                resource_id=session_id,
                details={
                    "reason": INTERRUPTED_BY_RESTART,
                    "trigger": trigger,
                    "session_settled": int(session_id in settled_session_ids),
                    "attempts_settled": attempt_counts[session_id],
                },
            )
        )
    pruned = await prune_expired_process_leases(db)
    await db.flush()
    result = InterruptionSettlement(sessions=len(sessions), attempts=len(attempts), pruned_leases=pruned,
                                    paused_runs=len(paused_runs), task_runs=len(task_runs))
    if result.sessions or result.attempts or result.task_runs:
        logger.warning(
            "interrupted_turns_settled",
            extra={"trigger": trigger, "sessions": result.sessions, "attempts": result.attempts,
                   "paused_runs": result.paused_runs, "task_runs": result.task_runs},
        )
    return result


__all__ = [
    "AUDIT_ACTION",
    "TRIGGER_STARTUP",
    "TRIGGER_SWEEP",
    "InterruptionSettlement",
    "settle_interrupted_turns",
]
