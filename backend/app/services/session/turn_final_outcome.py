"""The final outcome of one Action run's agent turn."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_reply_contract_schema import STATUS_SATISFIED, STATUS_VIOLATED
from app.services.session.reply_contract import REASON_UNCHECKED

from ...models import Message, TurnTrace
from .turn_execution_snapshot import (
    RUNTIME_OUTCOME_STOPPED,
    RUNTIME_STOP_REASON_KEY,
    RUNTIME_STOP_REASONS,
    RUNTIME_STOP_REPLY_CONTRACT_REASONS,
    read_agent_reply_contract,
    read_turn_execution_snapshot,
)
from .turn_execution_summary import runtime_outcome_from_trace

_UNRECORDED_OUTCOME = "unknown"


def _precedes(boundary_at: datetime | None, ids_at: frozenset[str], row_id: str, created_at: datetime) -> bool:
    if boundary_at is None:
        return False
    return created_at < boundary_at or (created_at == boundary_at and row_id in ids_at)


@dataclass(frozen=True, slots=True)
class TraceBoundary:
    created_at: datetime | None
    trace_ids_at: frozenset[str]
    message_created_at: datetime | None = None
    message_ids_at: frozenset[str] = frozenset()

    def precedes(self, trace_id: str, created_at: datetime) -> bool:
        return _precedes(self.created_at, self.trace_ids_at, trace_id, created_at)

    def precedes_message(self, message_id: str, created_at: datetime) -> bool:
        return _precedes(self.message_created_at, self.message_ids_at, message_id, created_at)


@dataclass(frozen=True, slots=True)
class TurnFinalOutcome:
    trace_id: str
    #: ``finished`` | ``stopped`` | ``failed`` (``runtime_outcome_from_trace``; never ``unknown``).
    outcome: str
    #: The closed runtime stop reason of a ``stopped`` trace, else ``None``.
    stop_reason: str | None
    #: The closed reply-contract record (``read_agent_reply_contract``), else ``None``.
    reply_contract: dict[str, Any] | None


async def _newest(db: AsyncSession, model: Any, *conditions: Any) -> tuple[datetime | None, frozenset[str]]:
    newest = (await db.execute(select(func.max(model.created_at)).where(*conditions))).scalar_one_or_none()
    if newest is None:
        return None, frozenset()
    ids = (await db.execute(select(model.id).where(*conditions, model.created_at == newest))).scalars()
    return newest, frozenset(ids)


def _user_messages(session_id: str) -> tuple[Any, ...]:
    return (Message.session_id == session_id, Message.role == "user")


async def capture_trace_boundary(db: AsyncSession, session_id: str) -> TraceBoundary:
    # Call it immediately before the run's ``run_agent``.
    trace_at, trace_ids = await _newest(db, TurnTrace, TurnTrace.session_id == session_id)
    message_at, message_ids = await _newest(db, Message, *_user_messages(session_id))
    return TraceBoundary(trace_at, trace_ids, message_at, message_ids)


async def _foreign_turn_after(db: AsyncSession, session_id: str, boundary: TraceBoundary) -> bool:
    query = select(Message.id, Message.created_at).where(*_user_messages(session_id))
    if boundary.message_created_at is not None:
        query = query.where(Message.created_at >= boundary.message_created_at)
    return any(not boundary.precedes_message(row.id, row.created_at) for row in (await db.execute(query)).all())


async def load_run_final_outcome(
    db: AsyncSession, session_id: str, boundary: TraceBoundary
) -> TurnFinalOutcome | None:
    # ``None`` unless exactly one final trace exists and it is the latest, and also when a user message was written
    # after the boundary.
    if await _foreign_turn_after(db, session_id, boundary):
        return None
    query = select(TurnTrace.id, TurnTrace.created_at, TurnTrace.context_snapshot_json, TurnTrace.raw_output).where(
        TurnTrace.session_id == session_id
    )
    if boundary.created_at is not None:
        query = query.where(TurnTrace.created_at >= boundary.created_at)
    rows = [
        row
        for row in (await db.execute(query.order_by(TurnTrace.created_at.asc(), TurnTrace.id.asc()))).all()
        if not boundary.precedes(row.id, row.created_at)
    ]
    finals = [
        (index, row, outcome)
        for index, row in enumerate(rows)
        if (outcome := runtime_outcome_from_trace(row.context_snapshot_json, row.raw_output)) != _UNRECORDED_OUTCOME
    ]
    if len(finals) != 1:
        return None
    index, row, outcome = finals[0]
    if index != len(rows) - 1:
        return None
    _status, snapshot = read_turn_execution_snapshot(row.context_snapshot_json)
    return TurnFinalOutcome(
        trace_id=row.id,
        outcome=outcome,
        stop_reason=snapshot[RUNTIME_STOP_REASON_KEY] if snapshot is not None else None,
        reply_contract=read_agent_reply_contract(row.context_snapshot_json),
    )


async def load_run_turn_error_class(
    db: AsyncSession, session_id: str, boundary: TraceBoundary
) -> str | None:
    from ..content_security.refusal import recorded_turn_error_class

    query = select(TurnTrace.id, TurnTrace.created_at, TurnTrace.raw_output).where(TurnTrace.session_id == session_id)
    if boundary.created_at is not None:
        query = query.where(TurnTrace.created_at >= boundary.created_at)
    rows = [
        row
        for row in (await db.execute(query.order_by(TurnTrace.created_at.asc(), TurnTrace.id.asc()))).all()
        if not boundary.precedes(row.id, row.created_at)
    ]
    return recorded_turn_error_class(rows[-1].raw_output) if rows else None


def action_reply_verdict(final: TurnFinalOutcome | None) -> str | None:
    if final is None:
        return REASON_UNCHECKED
    record = final.reply_contract
    if record is not None and record["status"] == STATUS_VIOLATED:
        return record["reason"]
    if final.outcome == "stopped" and final.stop_reason in RUNTIME_STOP_REPLY_CONTRACT_REASONS:
        return final.stop_reason
    if final.outcome == "finished" and record is not None and record["status"] == STATUS_SATISFIED:
        return None
    return REASON_UNCHECKED


def action_stop_verdict(final: TurnFinalOutcome | None) -> str | None:
    if final is None or final.outcome != RUNTIME_OUTCOME_STOPPED:
        return None
    return final.stop_reason if final.stop_reason in RUNTIME_STOP_REASONS else None


__all__ = [
    "TraceBoundary",
    "TurnFinalOutcome",
    "action_reply_verdict",
    "action_stop_verdict",
    "capture_trace_boundary",
    "load_run_final_outcome",
    "load_run_turn_error_class",
]
