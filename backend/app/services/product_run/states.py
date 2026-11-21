"""Closed Product Run lifecycle: legal transitions and end reasons.

The vocabulary lives on the model (``app.models.runtime.product_run``); this
module decides which moves between those states are legal, which end reason may
accompany each move, and which execution-gate facts a gate decision carries.
Nothing here performs I/O.

``completed`` and ``verifying`` are reserved for a verification contract: the
database accepts them, no transition reaches them. A finished turn ends at best
as ``finished_unverified``.
"""

from __future__ import annotations

from types import MappingProxyType

from app.services.execution_profile_status import (
    EXECUTION_PROFILE_STATUS_ALLOWED,
    EXECUTION_PROFILE_STATUS_DENIED,
    EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL,
    EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION,
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
)

from ...models.runtime.product_run import (
    RUN_END_REASONS,
    RUN_STATE_ADMITTED,
    RUN_STATE_CANCELLED,
    RUN_STATE_COMPLETED,
    RUN_STATE_DENIED,
    RUN_STATE_FAILED,
    RUN_STATE_FINISHED_UNVERIFIED,
    RUN_STATE_INCOMPLETE,
    RUN_STATE_NEEDS_APPROVAL,
    RUN_STATE_NEEDS_CLARIFICATION,
    RUN_STATE_NEEDS_CONFIGURATION,
    RUN_STATE_REQUESTED,
    RUN_STATE_RUNNING,
    RUN_STATE_VERIFYING,
    RUN_STATE_WAITING_APPROVAL,
    RUN_STATES,
)
from ..session.execution_gate import (
    GATE_SOURCE_MISSING_PROFILE,
    GATE_SOURCE_PROFILE,
    GATE_SOURCE_UNKNOWN_STATUS,
    GATE_SOURCE_WORKFLOW_PROPOSAL,
    GATE_STATUS_NEEDS_CONFIRMATION,
)

INITIAL_STATE = RUN_STATE_REQUESTED

ACTIVE_STATES = frozenset({RUN_STATE_REQUESTED, RUN_STATE_ADMITTED, RUN_STATE_RUNNING})
RESERVED_STATES = frozenset({RUN_STATE_VERIFYING, RUN_STATE_COMPLETED})
TERMINAL_STATES = frozenset(RUN_STATES) - ACTIVE_STATES - RESERVED_STATES

LEGAL_TRANSITIONS: MappingProxyType[str, frozenset[str]] = MappingProxyType(
    {
        RUN_STATE_REQUESTED: frozenset(
            {
                RUN_STATE_ADMITTED,
                RUN_STATE_DENIED,
                RUN_STATE_NEEDS_APPROVAL,
                RUN_STATE_NEEDS_CONFIGURATION,
                RUN_STATE_NEEDS_CLARIFICATION,
                RUN_STATE_FAILED,
                RUN_STATE_CANCELLED,
            }
        ),
        RUN_STATE_ADMITTED: frozenset(
            {
                RUN_STATE_RUNNING,
                RUN_STATE_NEEDS_CONFIGURATION,
                RUN_STATE_FAILED,
                RUN_STATE_CANCELLED,
            }
        ),
        RUN_STATE_RUNNING: frozenset(
            {
                RUN_STATE_FINISHED_UNVERIFIED,
                # The model gateway's admission refused every runtime target.
                RUN_STATE_NEEDS_CONFIGURATION,
                RUN_STATE_DENIED,
                RUN_STATE_FAILED,
                RUN_STATE_CANCELLED,
                RUN_STATE_WAITING_APPROVAL,
                RUN_STATE_NEEDS_CLARIFICATION,
                RUN_STATE_INCOMPLETE,
            }
        ),
    }
)

_FROM_REQUESTED = frozenset({RUN_STATE_REQUESTED})
_FROM_ADMITTED = frozenset({RUN_STATE_ADMITTED})
_FROM_RUNNING = frozenset({RUN_STATE_RUNNING})
_FROM_ANY_ACTIVE = frozenset({RUN_STATE_REQUESTED, RUN_STATE_ADMITTED, RUN_STATE_RUNNING})

# Every end reason names the one terminal state it produces and the states it may
# leave, so the audit can never record a cause that contradicts where the attempt
# came from (a gate block for a running attempt, a provider error before admission).
END_REASON_RULES: MappingProxyType[str, tuple[str, frozenset[str]]] = MappingProxyType(
    {
        "gate_denied": (RUN_STATE_DENIED, _FROM_REQUESTED),
        "gate_missing_profile": (RUN_STATE_DENIED, _FROM_REQUESTED),
        "gate_unknown_status": (RUN_STATE_DENIED, _FROM_REQUESTED),
        "gate_needs_approval": (RUN_STATE_NEEDS_APPROVAL, _FROM_REQUESTED),
        "gate_needs_configuration": (RUN_STATE_NEEDS_CONFIGURATION, _FROM_REQUESTED),
        "gate_needs_clarification": (RUN_STATE_NEEDS_CLARIFICATION, _FROM_REQUESTED),
        # A workflow proposal waits for the user's confirmation on its approval record.
        "awaiting_workflow_confirmation": (RUN_STATE_NEEDS_APPROVAL, _FROM_REQUESTED),
        "preparation_failed": (RUN_STATE_FAILED, _FROM_REQUESTED),
        "runtime_not_ready": (RUN_STATE_NEEDS_CONFIGURATION, _FROM_ADMITTED),
        "model_alias_not_admitted": (RUN_STATE_NEEDS_CONFIGURATION, _FROM_RUNNING),
        "model_data_policy_denied": (RUN_STATE_DENIED, _FROM_RUNNING),
        "runtime_finished": (RUN_STATE_FINISHED_UNVERIFIED, _FROM_RUNNING),
        "provider_error": (RUN_STATE_FAILED, _FROM_RUNNING),
        "runtime_error": (RUN_STATE_FAILED, _FROM_RUNNING),
        "runtime_exception": (RUN_STATE_FAILED, _FROM_ANY_ACTIVE),
        "approval_pending": (RUN_STATE_WAITING_APPROVAL, _FROM_RUNNING),
        "clarification_requested": (RUN_STATE_NEEDS_CLARIFICATION, _FROM_RUNNING),
        "completion_not_accepted": (RUN_STATE_INCOMPLETE, _FROM_RUNNING),
        "delegated_outcome_unrecorded": (RUN_STATE_INCOMPLETE, _FROM_RUNNING),
        "generator_closed": (RUN_STATE_CANCELLED, _FROM_ANY_ACTIVE),
        "task_cancelled": (RUN_STATE_CANCELLED, _FROM_ANY_ACTIVE),
        # The process that owned the active attempt died (restart or crash): settled by
        # ``services/product_run/interruption.py``, never produced by a live turn.
        "interrupted_by_restart": (RUN_STATE_FAILED, _FROM_ANY_ACTIVE),
    }
)
END_REASON_STATES: MappingProxyType[str, str] = MappingProxyType(
    {reason: target for reason, (target, _sources) in END_REASON_RULES.items()}
)

if frozenset(END_REASON_RULES) != frozenset(RUN_END_REASONS):  # pragma: no cover - import-time contract
    raise RuntimeError("END_REASON_RULES must cover exactly the model's RUN_END_REASONS")

# Execution-gate facts are recorded exactly once: on the move that leaves
# ``requested`` because of the gate's decision. Each gate end reason (and
# admission) fixes the gate status and decision source it may carry.
GATE_DECIDED_STATES = frozenset(
    {
        RUN_STATE_ADMITTED,
        RUN_STATE_DENIED,
        RUN_STATE_NEEDS_APPROVAL,
        RUN_STATE_NEEDS_CONFIGURATION,
        RUN_STATE_NEEDS_CLARIFICATION,
    }
)
_ANY_GATE_STATUS = None
_GATE_FACT_RULES: MappingProxyType[str | None, tuple[str | None, str]] = MappingProxyType(
    {
        None: (EXECUTION_PROFILE_STATUS_ALLOWED, GATE_SOURCE_PROFILE),  # admission carries no end reason
        "gate_denied": (EXECUTION_PROFILE_STATUS_DENIED, GATE_SOURCE_PROFILE),
        "gate_missing_profile": (EXECUTION_PROFILE_STATUS_DENIED, GATE_SOURCE_MISSING_PROFILE),
        "gate_unknown_status": (_ANY_GATE_STATUS, GATE_SOURCE_UNKNOWN_STATUS),
        "gate_needs_approval": (EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL, GATE_SOURCE_PROFILE),
        "gate_needs_configuration": (EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION, GATE_SOURCE_PROFILE),
        "gate_needs_clarification": (EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION, GATE_SOURCE_PROFILE),
        "awaiting_workflow_confirmation": (GATE_STATUS_NEEDS_CONFIRMATION, GATE_SOURCE_WORKFLOW_PROPOSAL),
    }
)


def is_legal_transition(from_state: str, to_state: str) -> bool:
    """Return whether ``from_state`` may move to ``to_state``."""
    return to_state in LEGAL_TRANSITIONS.get(from_state, frozenset())


def is_legal_end_reason(from_state: str, to_state: str, end_reason: str | None) -> bool:
    """Terminal moves need a reason that produces ``to_state`` from ``from_state``; others take none."""
    if to_state in TERMINAL_STATES:
        rule = END_REASON_RULES.get(end_reason) if end_reason is not None else None
        return rule is not None and rule[0] == to_state and from_state in rule[1]
    return end_reason is None


def requires_gate_facts(from_state: str, to_state: str) -> bool:
    """Gate facts belong to, and only to, the gate's decision on a requested attempt."""
    return from_state == RUN_STATE_REQUESTED and to_state in GATE_DECIDED_STATES


def gate_facts_match(end_reason: str | None, status: str, decision_source: str) -> bool:
    """Return whether the gate's status and source are the ones this decision implies."""
    if end_reason not in _GATE_FACT_RULES:
        return False
    expected_status, expected_source = _GATE_FACT_RULES[end_reason]
    return decision_source == expected_source and expected_status in (_ANY_GATE_STATUS, status)


__all__ = [
    "ACTIVE_STATES",
    "END_REASON_RULES",
    "END_REASON_STATES",
    "GATE_DECIDED_STATES",
    "INITIAL_STATE",
    "LEGAL_TRANSITIONS",
    "RESERVED_STATES",
    "TERMINAL_STATES",
    "gate_facts_match",
    "is_legal_end_reason",
    "is_legal_transition",
    "requires_gate_facts",
]
