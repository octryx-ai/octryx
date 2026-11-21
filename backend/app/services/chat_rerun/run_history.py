"""Append-only run history across a chat re-run.

A re-run replaces the conversation after the target message, but what already happened stays
recorded: approvals, turn traces and usage events are never deleted. The
replaced run's records are marked superseded instead — a still-pending approval is cancelled
so it cannot be decided into the new run, and traces drop their link to
the removed message while keeping it in a ``superseded`` marker. Usage events are left as they
are: the spend happened and still counts.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, TurnTrace
from ..decisions.approvals import record_approval_decided

SUPERSEDED_MARKER_KEY = "superseded"
SUPERSEDED_REASON_CHAT_RERUN = "chat_rerun"
RERUN_CANCELLED_APPROVAL_STATUS = "cancelled"
RERUN_CANCELLED_APPROVAL_REASON = "Superseded by a chat re-run"


def _superseded_marker(*, message_id: str | None, superseded_at: datetime) -> dict:
    return {
        "reason": SUPERSEDED_REASON_CHAT_RERUN,
        "at": superseded_at.isoformat(),
        "message_id": message_id,
    }


def _in_window(column_created_at, column_message_id, *, cutoff: datetime, later_message_ids: list[str]):
    if later_message_ids:
        return or_(column_created_at > cutoff, column_message_id.in_(later_message_ids))
    return column_created_at > cutoff


async def _cancel_pending_approvals(
    db: AsyncSession, *, session_id: str, cutoff: datetime, superseded_at: datetime
) -> None:
    pending_approvals = (
        (
            await db.execute(
                select(Approval).where(
                    Approval.session_id == session_id,
                    Approval.created_at > cutoff,
                    Approval.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    for approval in pending_approvals:
        approval.status = RERUN_CANCELLED_APPROVAL_STATUS
        approval.resolved_at = superseded_at
        # The request's reason stays; the cancellation is the decision note and a decision record (O2).
        approval.decision_note = RERUN_CANCELLED_APPROVAL_REASON
        await record_approval_decided(db, approval)


async def _supersede_traces(
    db: AsyncSession, *, session_id: str, cutoff: datetime, later_message_ids: list[str], superseded_at: datetime
) -> None:
    traces = (
        (
            await db.execute(
                select(TurnTrace).where(
                    TurnTrace.session_id == session_id,
                    _in_window(
                        TurnTrace.created_at, TurnTrace.message_id, cutoff=cutoff, later_message_ids=later_message_ids
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for trace in traces:
        snapshot = dict(trace.context_snapshot_json or {})
        snapshot[SUPERSEDED_MARKER_KEY] = _superseded_marker(message_id=trace.message_id, superseded_at=superseded_at)
        trace.context_snapshot_json = snapshot
        trace.message_id = None


async def supersede_rerun_history(
    db: AsyncSession,
    *,
    session_id: str,
    cutoff: datetime,
    later_message_ids: list[str],
    superseded_at: datetime,
) -> None:
    """Mark the replaced run's approvals and traces superseded (no deletes)."""
    await _cancel_pending_approvals(db, session_id=session_id, cutoff=cutoff, superseded_at=superseded_at)
    window = {"session_id": session_id, "cutoff": cutoff, "later_message_ids": later_message_ids}
    await _supersede_traces(db, **window, superseded_at=superseded_at)
    await db.flush()


__all__ = [
    "RERUN_CANCELLED_APPROVAL_REASON",
    "RERUN_CANCELLED_APPROVAL_STATUS",
    "SUPERSEDED_MARKER_KEY",
    "supersede_rerun_history",
]
