"""Turn admission at the execution boundary: gate, snapshot binding, blocked turns.

``run_agent`` admits a prepared turn here before any loop starts. This is the
single place that evaluates the execution gate (``evaluate_execution_gate``), and it
runs for every caller:

1. the gate decides on the turn's frozen execution profile;
2. the bounded turn execution snapshot is bound for the session, carrying the
   Product Run stamp when the caller bound the turn to a run, so every
   ``TurnTrace`` of the turn records it, blocked turns included;
3. a blocked gate persists its explanation as the turn's traced assistant message
   (the loop never runs, so nothing else would persist it); a turn held for a workflow
   proposal also gets its one governed approval record (``workflow_routing/proposal_approval``);
4. an allowed turn still stops when no runtime target is executable (readiness
   block, persisted by ``block_turn_without_ready_runtime``).

The result says which of the three outcomes happened; the caller yields the
blocked message and returns without starting a loop.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...services.decisions.gates import count_admitted_turn
from ...services.product_run.turn_stamp import PRODUCT_RUN_STAMP_KEY
from ...services.session.execution_gate import (
    GATE_SOURCE_WORKFLOW_PROPOSAL,
    ExecutionGateDecision,
    evaluate_execution_gate,
)
from ...services.session.turn_execution_snapshot import build_turn_execution_snapshot
from ...services.workflow_routing.proposal_approval import request_workflow_proposal_approval
from ..core.runtime.trace_runtime import gate_trace_context_snapshot
from ..core.runtime.turn_execution_binding import bind_turn_execution_snapshot
from .pre_dispatch._runtime_readiness_block import block_turn_without_ready_runtime

logger = logging.getLogger(__name__)

TURN_ADMITTED = "admitted"
TURN_BLOCKED_BY_EXECUTION_GATE = "blocked_by_execution_gate"
TURN_BLOCKED_BY_RUNTIME_READINESS = "blocked_by_runtime_readiness"


@dataclass(frozen=True, slots=True)
class TurnAdmission:
    """The admission outcome of one turn and, when blocked, the persisted explanation."""

    outcome: str
    gate: ExecutionGateDecision
    execution_profile: Any
    blocked_message: str | None = None

    @property
    def admitted(self) -> bool:
        return self.outcome == TURN_ADMITTED


async def _phased_start_message(db: AsyncSession, session_id: str) -> str | None:
    """A phased start's held turn names the start it waits for (``phased_start.held_turn_message``)."""
    from ...models import Session
    from ...services.workflow_routing.phased_start import held_turn_message

    session = await db.get(Session, session_id)
    return held_turn_message(session) if session is not None else None


async def admit_turn(
    *,
    db: AsyncSession,
    session_id: str,
    prepared: Any,
    agent_definition: dict | None,
    runtime_target_id: str | None,
    product_run_stamp: dict[str, Any] | None,
    resolve_runtimes_func: Callable[..., Awaitable[list[dict[str, Any]]]],
    persist_traced_assistant_message_func: Callable[..., Awaitable[Any]],
) -> TurnAdmission:
    """Evaluate the gate, bind the turn snapshot, and persist a blocked turn's explanation."""
    execution_profile = prepared.session_metadata.get("execution_profile")
    execution_gate = evaluate_execution_gate(execution_profile)
    snapshot = build_turn_execution_snapshot(
        execution_profile=execution_profile,
        gate=execution_gate,
        session_metadata=prepared.session_metadata,
        agent_definition=agent_definition,
    )
    if product_run_stamp is not None:
        snapshot[PRODUCT_RUN_STAMP_KEY] = dict(product_run_stamp)
    bind_turn_execution_snapshot(session_id, snapshot)
    trace_context_snapshot = gate_trace_context_snapshot(prepared.tool_context)
    if not execution_gate.allowed:
        logger.info(
            "agent.run.blocked_by_execution_profile",
            extra={
                "session_id": session_id,
                "profile_status": execution_gate.status,
                "decision_source": execution_gate.decision_source,
                "reason": execution_gate.reason,
            },
        )
        blocked_message = execution_gate.user_message
        if execution_gate.decision_source == GATE_SOURCE_WORKFLOW_PROPOSAL:
            await request_workflow_proposal_approval(db, session_id=session_id)
            blocked_message = await _phased_start_message(db, session_id) or blocked_message
        # Assistant messages are persisted by the loop, not the event consumers;
        # a gate-blocked turn must persist its explanation itself or the user
        # sees a silently completed turn.
        await persist_traced_assistant_message_func(
            db=db,
            session_id=session_id,
            content=blocked_message,
            provider="execution-gate",
            model="",
            input_messages=[],
            context_snapshot=trace_context_snapshot,
            raw_output=execution_gate.trace_output(),
        )
        return TurnAdmission(TURN_BLOCKED_BY_EXECUTION_GATE, execution_gate, execution_profile, blocked_message)
    runtime_blocked_message = await block_turn_without_ready_runtime(
        db=db,
        session_id=session_id,
        runtimes=prepared.runtimes,
        runtime_target_id=runtime_target_id,
        resolve_runtimes_func=resolve_runtimes_func,
        persist_traced_assistant_message_func=persist_traced_assistant_message_func,
        trace_context_snapshot=trace_context_snapshot,
    )
    if runtime_blocked_message is not None:
        return TurnAdmission(
            TURN_BLOCKED_BY_RUNTIME_READINESS, execution_gate, execution_profile, runtime_blocked_message
        )
    count_admitted_turn(getattr(prepared.tool_context, "project_ids", None))
    return TurnAdmission(TURN_ADMITTED, execution_gate, execution_profile)


__all__ = [
    "TURN_ADMITTED",
    "TURN_BLOCKED_BY_EXECUTION_GATE",
    "TURN_BLOCKED_BY_RUNTIME_READINESS",
    "TurnAdmission",
    "admit_turn",
]
