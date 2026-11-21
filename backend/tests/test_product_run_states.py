"""The Product Run lifecycle table is closed; the reserved states have no producer."""

from __future__ import annotations

from collections import deque

import pytest

from app.models.runtime.product_run import (
    RUN_END_REASONS,
    RUN_STATE_COMPLETED,
    RUN_STATE_VERIFYING,
    RUN_STATES,
)
from app.services.product_run.states import (
    ACTIVE_STATES,
    END_REASON_RULES,
    END_REASON_STATES,
    GATE_DECIDED_STATES,
    INITIAL_STATE,
    LEGAL_TRANSITIONS,
    RESERVED_STATES,
    TERMINAL_STATES,
    gate_facts_match,
    is_legal_end_reason,
    is_legal_transition,
    requires_gate_facts,
)


def _reachable_from_initial() -> set[str]:
    seen = {INITIAL_STATE}
    queue = deque([INITIAL_STATE])
    while queue:
        for target in LEGAL_TRANSITIONS.get(queue.popleft(), frozenset()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def test_state_partition_covers_the_model_vocabulary_exactly() -> None:
    assert ACTIVE_STATES | RESERVED_STATES | TERMINAL_STATES == set(RUN_STATES)
    assert not ACTIVE_STATES & RESERVED_STATES
    assert not ACTIVE_STATES & TERMINAL_STATES
    assert not RESERVED_STATES & TERMINAL_STATES
    assert RESERVED_STATES == {RUN_STATE_VERIFYING, RUN_STATE_COMPLETED}


def test_only_active_states_have_outgoing_moves_and_every_target_is_known() -> None:
    assert set(LEGAL_TRANSITIONS) == ACTIVE_STATES
    for targets in LEGAL_TRANSITIONS.values():
        assert targets <= set(RUN_STATES)
    for state in TERMINAL_STATES | RESERVED_STATES:
        assert not any(is_legal_transition(state, target) for target in RUN_STATES)


def test_every_non_reserved_state_is_reachable_and_reserved_states_are_not() -> None:
    reachable = _reachable_from_initial()
    assert reachable == ACTIVE_STATES | TERMINAL_STATES
    assert not reachable & RESERVED_STATES
    assert RESERVED_STATES == {RUN_STATE_COMPLETED, RUN_STATE_VERIFYING}


def test_end_reasons_map_onto_terminal_states_from_active_sources() -> None:
    # Every reason is a move out of an active state.
    assert set(END_REASON_RULES) == set(RUN_END_REASONS)
    for target, sources in END_REASON_RULES.values():
        assert target in TERMINAL_STATES
        assert sources and sources <= ACTIVE_STATES
        assert all(is_legal_transition(source, target) for source in sources)
    # Every terminal state can be reached with at least one reason.
    assert set(END_REASON_STATES.values()) == TERMINAL_STATES


def test_every_legal_terminal_move_has_a_reason_and_every_reason_fits_only_its_moves() -> None:
    for source, targets in LEGAL_TRANSITIONS.items():
        for target in targets & TERMINAL_STATES:
            assert any(is_legal_end_reason(source, target, reason) for reason in RUN_END_REASONS), (source, target)
    for reason, (target, sources) in END_REASON_RULES.items():
        for state in ACTIVE_STATES:
            assert is_legal_end_reason(state, target, reason) is (state in sources)


@pytest.mark.parametrize(
    ("source", "target", "reason"),
    [
        ("running", "needs_clarification", "gate_needs_clarification"),  # gate block after admission
        ("requested", "failed", "provider_error"),  # provider cause before admission
        ("requested", "needs_clarification", "clarification_requested"),
        ("running", "needs_configuration", "runtime_not_ready"),
    ],
)
def test_a_reason_that_contradicts_the_source_is_refused(source: str, target: str, reason: str) -> None:
    assert not is_legal_end_reason(source, target, reason)


@pytest.mark.parametrize("state", sorted(ACTIVE_STATES))
def test_active_targets_refuse_any_end_reason(state: str) -> None:
    for source in ACTIVE_STATES:
        assert is_legal_end_reason(source, state, None)
        assert not any(is_legal_end_reason(source, state, reason) for reason in RUN_END_REASONS)


@pytest.mark.parametrize("state", sorted(TERMINAL_STATES))
def test_terminal_targets_require_a_reason(state: str) -> None:
    for source in ACTIVE_STATES:
        assert not is_legal_end_reason(source, state, None)


def test_gate_facts_belong_only_to_the_gate_decision_on_a_requested_attempt() -> None:
    for source in ACTIVE_STATES:
        for target in LEGAL_TRANSITIONS[source]:
            expected = source == "requested" and target in GATE_DECIDED_STATES
            assert requires_gate_facts(source, target) is expected
    assert not requires_gate_facts("requested", "failed")
    assert not requires_gate_facts("requested", "cancelled")


def test_gate_facts_must_equal_the_decision_they_record() -> None:
    assert gate_facts_match(None, "allowed", "execution_profile")
    assert not gate_facts_match(None, "denied", "execution_profile")
    assert gate_facts_match("gate_denied", "denied", "execution_profile")
    assert not gate_facts_match("gate_denied", "denied", "missing_profile")
    assert gate_facts_match("gate_missing_profile", "denied", "missing_profile")
    assert not gate_facts_match("gate_missing_profile", "missing", "missing_profile")
    assert gate_facts_match("gate_unknown_status", "unknown", "unknown_execution_profile_status")
    assert not gate_facts_match("gate_unknown_status", "unknown", "execution_profile")
    assert not gate_facts_match("runtime_not_ready", "needs_configuration", "execution_profile")


def test_unknown_values_are_refused() -> None:
    assert not is_legal_transition("requested", "done")
    assert not is_legal_transition("unknown", "running")
    assert not is_legal_end_reason("running", "failed", "because")
