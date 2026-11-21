"""Map a Chat turn's explicit facts onto Product Run moves.

The Chat binding (``agent/engine/_engine_product_run.py``) asks this module which
move a turn's gate decision, readiness block, or end implies. Every mapping is a
closed table over explicit markers the runtime already writes; nothing here reads
message content or guesses intent.

Gate decision (from ``requested``):

* allowed                                   -> ``admitted`` (gate facts recorded)
* execution profile ``denied``              -> ``denied`` / ``gate_denied``
* execution profile ``needs_approval``      -> ``needs_approval`` / ``gate_needs_approval``
* execution profile ``needs_configuration`` -> ``needs_configuration`` / ``gate_needs_configuration``
* execution profile ``needs_clarification`` -> ``needs_clarification`` / ``gate_needs_clarification``
* workflow proposal ``needs_confirmation``   -> ``needs_approval`` / ``awaiting_workflow_confirmation``
  (the held turn waits on the proposal's governed approval record)
* missing profile (gate ``denied``)         -> ``denied`` / ``gate_missing_profile``
* unknown profile status                    -> ``denied`` / ``gate_unknown_status``

Readiness block (from ``admitted``): ``needs_configuration`` / ``runtime_not_ready``.

Turn end (from ``running``), decided on the turn's final stamped trace and the
session's own status, first match wins:

1. the final trace carries the runtime's ``raw_output.error`` failure marker.
   When the trace is the provider-dispatch failure record (trace provider
   ``runtime-fallback``, written by the native loop and the harness recorder
   alike) and the model gateway's admission refused every runtime target before
   any request (typed attempt facts, ``admission_refusal_of_attempts``), the turn
   is a governance outcome, not a provider error:
   ``needs_configuration`` / ``model_alias_not_admitted`` for an alias the
   project was not granted (an administrator can grant it), ``denied`` /
   ``model_data_policy_denied`` when the Workspace's data classification is not
   permitted for the alias (policy forbids it). Any other dispatch failure is
   ``failed`` / ``provider_error``; a failure elsewhere ``failed`` / ``runtime_error``;
2. the session is ``pending_approval`` (set by the approval request service):
   ``waiting_approval`` / ``approval_pending``;
3. the session is ``awaiting_subagents``: ``incomplete`` / ``delegated_outcome_unrecorded``;
4. the final trace carries the loop's accepted-completion marker:
   ``finished_unverified`` / ``runtime_finished``;
5. anything else, including no stamped trace at all: ``incomplete`` /
   ``completion_not_accepted``.

``completed`` is never produced: it is reserved for a verification contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.execution_profile_status import (
    EXECUTION_PROFILE_STATUS_DENIED,
    EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL,
    EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION,
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
)

from ...agent.core.runtime.runtime_admission_contract import admission_refusal_of_attempts
from ...agent.core.runtime.runtime_errors import (
    RUNTIME_ERROR_ALIAS_DENIED,
    RUNTIME_ERROR_CONTENT_POLICY_DENIED,
    RUNTIME_ERROR_DATA_POLICY_DENIED,
)
from ...models import Session as ChatSession
from ...models import TurnTrace
from ...models.runtime.product_run import (
    RUN_STATE_ADMITTED,
    RUN_STATE_DENIED,
    RUN_STATE_FAILED,
    RUN_STATE_FINISHED_UNVERIFIED,
    RUN_STATE_INCOMPLETE,
    RUN_STATE_NEEDS_APPROVAL,
    RUN_STATE_NEEDS_CLARIFICATION,
    RUN_STATE_NEEDS_CONFIGURATION,
    RUN_STATE_WAITING_APPROVAL,
)
from ..session.execution_gate import (
    GATE_SOURCE_MISSING_PROFILE,
    GATE_SOURCE_PROFILE,
    GATE_SOURCE_UNKNOWN_STATUS,
    GATE_SOURCE_WORKFLOW_PROPOSAL,
    GATE_STATUS_NEEDS_CONFIRMATION,
    ExecutionGateDecision,
)
from ..session.turn_execution_snapshot import (
    GATE_STATUSES,
    RUNTIME_OUTCOME_FINISHED,
    RUNTIME_OUTCOME_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
    UNKNOWN_VALUE,
    bounded_sequence,
    read_turn_execution_snapshot,
    safe_token,
)
from .service import GateFacts
from .turn_stamp import STAMP_BOUND, read_product_run_stamp

# Trace provider of the runtime's provider-dispatch failure record.
PROVIDER_FAILURE_TRACE_PROVIDER = "runtime-fallback"
SESSION_STATUS_PENDING_APPROVAL = "pending_approval"
SESSION_STATUS_AWAITING_SUBAGENTS = "awaiting_subagents"
_EXECUTION_PROFILE_ID_MAX = 160


@dataclass(frozen=True, slots=True)
class RunMove:
    """One state move of the turn's attempt."""

    to_state: str
    end_reason: str | None = None
    gate: GateFacts | None = None


@dataclass(frozen=True, slots=True)
class FinalTraceFacts:
    """The explicit markers of a turn's final stamped trace."""

    provider: str
    failed: bool
    finished: bool
    # The admission class that refused every runtime target, if the failure was that.
    admission_refusal: str | None = None


_GATE_BLOCK_MOVES: dict[tuple[str, str], tuple[str, str]] = {
    (GATE_SOURCE_PROFILE, EXECUTION_PROFILE_STATUS_DENIED): (RUN_STATE_DENIED, "gate_denied"),
    (GATE_SOURCE_PROFILE, EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL): (RUN_STATE_NEEDS_APPROVAL, "gate_needs_approval"),
    (GATE_SOURCE_PROFILE, EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION): (
        RUN_STATE_NEEDS_CONFIGURATION,
        "gate_needs_configuration",
    ),
    (GATE_SOURCE_PROFILE, EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION): (
        RUN_STATE_NEEDS_CLARIFICATION,
        "gate_needs_clarification",
    ),
    (GATE_SOURCE_MISSING_PROFILE, EXECUTION_PROFILE_STATUS_DENIED): (RUN_STATE_DENIED, "gate_missing_profile"),
    (GATE_SOURCE_WORKFLOW_PROPOSAL, GATE_STATUS_NEEDS_CONFIRMATION): (
        RUN_STATE_NEEDS_APPROVAL,
        "awaiting_workflow_confirmation",
    ),
}

READINESS_BLOCK_MOVE = RunMove(RUN_STATE_NEEDS_CONFIGURATION, "runtime_not_ready")
_ADMISSION_REFUSAL_MOVES: dict[str, RunMove] = {
    RUNTIME_ERROR_ALIAS_DENIED: RunMove(RUN_STATE_NEEDS_CONFIGURATION, "model_alias_not_admitted"),
    RUNTIME_ERROR_DATA_POLICY_DENIED: RunMove(RUN_STATE_DENIED, "model_data_policy_denied"),
    # A content refusal is a data-policy denial of the run; the chat notice names the content policy.
    RUNTIME_ERROR_CONTENT_POLICY_DENIED: RunMove(RUN_STATE_DENIED, "model_data_policy_denied"),
}


def _profile_id(execution_profile: Any) -> str | None:
    profile = execution_profile if isinstance(execution_profile, dict) else {}
    token = safe_token(profile.get("profile_id"))
    return token if token is not None and len(token) <= _EXECUTION_PROFILE_ID_MAX else None


def gate_move(gate: ExecutionGateDecision, execution_profile: Any) -> RunMove | None:
    """The move the gate's decision implies, or ``None`` for a combination outside the table."""
    status = gate.status if gate.status in GATE_STATUSES else UNKNOWN_VALUE
    facts = GateFacts(
        status=status, decision_source=gate.decision_source, execution_profile_id=_profile_id(execution_profile)
    )
    if gate.allowed:
        return RunMove(RUN_STATE_ADMITTED, None, facts) if gate.decision_source == GATE_SOURCE_PROFILE else None
    if gate.decision_source == GATE_SOURCE_UNKNOWN_STATUS:
        return RunMove(RUN_STATE_DENIED, "gate_unknown_status", facts)
    blocked = _GATE_BLOCK_MOVES.get((gate.decision_source, gate.status))
    return RunMove(blocked[0], blocked[1], facts) if blocked is not None else None


def turn_end_move(final_trace: FinalTraceFacts | None, session_status: str | None) -> RunMove:
    """The terminal move of a turn whose loop returned normally (see the module table)."""
    if final_trace is not None and final_trace.failed:
        if final_trace.provider != PROVIDER_FAILURE_TRACE_PROVIDER:
            return RunMove(RUN_STATE_FAILED, "runtime_error")
        refused = _ADMISSION_REFUSAL_MOVES.get(final_trace.admission_refusal or "")
        return refused if refused is not None else RunMove(RUN_STATE_FAILED, "provider_error")
    if session_status == SESSION_STATUS_PENDING_APPROVAL:
        return RunMove(RUN_STATE_WAITING_APPROVAL, "approval_pending")
    if session_status == SESSION_STATUS_AWAITING_SUBAGENTS:
        return RunMove(RUN_STATE_INCOMPLETE, "delegated_outcome_unrecorded")
    if final_trace is not None and final_trace.finished:
        return RunMove(RUN_STATE_FINISHED_UNVERIFIED, "runtime_finished")
    return RunMove(RUN_STATE_INCOMPLETE, "completion_not_accepted")


def admission_refusal_of_trace(provider: Any, raw_output: Any) -> str | None:
    """The admission class that refused every target of a provider-dispatch failure record, or ``None``."""
    if str(provider or "") != PROVIDER_FAILURE_TRACE_PROVIDER or not isinstance(raw_output, dict):
        return None
    if not raw_output.get("error"):
        return None
    return admission_refusal_of_attempts(raw_output.get("runtime_attempts"))


def _trace_facts(provider: Any, context_snapshot: Any, raw_output: Any) -> FinalTraceFacts:
    _status, snapshot = read_turn_execution_snapshot(context_snapshot)
    finished = snapshot is not None and snapshot[RUNTIME_OUTCOME_KEY] == RUNTIME_OUTCOME_FINISHED
    failed = isinstance(raw_output, dict) and bool(raw_output.get("error"))
    return FinalTraceFacts(
        provider=str(provider or ""),
        failed=failed,
        finished=finished,
        admission_refusal=admission_refusal_of_trace(provider, raw_output),
    )


async def load_turn_end_move(
    db: AsyncSession,
    *,
    session_id: str,
    run_id: str,
    attempt_id: str,
    opened_at: datetime,
) -> RunMove:
    """Read the turn's final trace (highest stamped sequence of this attempt) and the session status."""
    rows = await db.execute(
        select(TurnTrace.provider, TurnTrace.context_snapshot_json, TurnTrace.raw_output).where(
            TurnTrace.session_id == session_id,
            TurnTrace.created_at >= opened_at,
        )
    )
    final: tuple[int, FinalTraceFacts] | None = None
    for provider, context_snapshot, raw_output in rows:
        stamp = read_product_run_stamp(context_snapshot)
        if stamp.status != STAMP_BOUND or stamp.run_id != run_id or stamp.attempt_id != attempt_id:
            continue
        # A bound stamp was read, so the context and its snapshot are dicts.
        turn = context_snapshot[TURN_EXECUTION_SNAPSHOT_KEY].get("turn")
        sequence = bounded_sequence(turn.get("sequence") if isinstance(turn, dict) else None)
        if sequence is not None and (final is None or sequence > final[0]):
            final = (sequence, _trace_facts(provider, context_snapshot, raw_output))
    session_status = (
        await db.execute(select(ChatSession.status).where(ChatSession.id == session_id))
    ).scalar_one_or_none()
    return turn_end_move(final[1] if final is not None else None, session_status)


__all__ = [
    "PROVIDER_FAILURE_TRACE_PROVIDER",
    "READINESS_BLOCK_MOVE",
    "FinalTraceFacts",
    "RunMove",
    "admission_refusal_of_trace",
    "gate_move",
    "load_turn_end_move",
    "turn_end_move",
]
