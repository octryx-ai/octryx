"""A turn held for a workflow confirmation ends its Product Run attempt explicitly.

``requested`` -> ``needs_approval`` / ``awaiting_workflow_confirmation`` (no more
``gate_decision_unmapped``). Revision ``a2c4e6f8b0d1`` adds the end reason to the three CHECK
constraints reversibly and refuses its downgrade while a row records it; on SQLite and, when
``OCTRYX_TEST_POSTGRES_URL`` is set, PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.models.runtime.product_run import RUN_END_REASONS
from app.services.product_run.states import END_REASON_RULES, gate_facts_match
from app.services.product_run.turn_outcome import RunMove, gate_move
from app.services.session.execution_gate import (
    GATE_SOURCE_WORKFLOW_PROPOSAL,
    GATE_STATUS_NEEDS_CONFIRMATION,
    ExecutionGateDecision,
)

END_REASON = "awaiting_workflow_confirmation"


def test_a_held_proposal_maps_to_needs_approval_with_the_confirmation_end_reason() -> None:
    held = ExecutionGateDecision(
        allowed=False,
        status=GATE_STATUS_NEEDS_CONFIRMATION,
        decision_source=GATE_SOURCE_WORKFLOW_PROPOSAL,
        reason="workflow proposal needs confirmation",
        user_message="",
    )
    move = gate_move(held, {"profile_id": "profile-1"})
    assert isinstance(move, RunMove)
    assert (move.to_state, move.end_reason) == ("needs_approval", END_REASON)
    assert (move.gate.status, move.gate.decision_source) == (GATE_STATUS_NEEDS_CONFIRMATION, "workflow_proposal")
    assert END_REASON in RUN_END_REASONS and END_REASON_RULES[END_REASON][0] == "needs_approval"
    assert gate_facts_match(END_REASON, GATE_STATUS_NEEDS_CONFIRMATION, GATE_SOURCE_WORKFLOW_PROPOSAL)


def _end_reasons(connection: Connection) -> dict[str, str]:
    from sqlalchemy import inspect

    inspector = inspect(connection)
    return {
        table: next(
            str(check["sqltext"])
            for check in inspector.get_check_constraints(table)
            if str(check.get("name", "")).endswith("_end_reason")
        )
        for table in ("product_runs", "product_run_attempts", "product_run_transitions")
    }


def _record_the_new_reason(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        # Only the CHECK constraint is under test: skip the foreign-key triggers for this transaction.
        connection.execute(text("SET LOCAL session_replication_role = replica"))
    connection.execute(
        text(
            "INSERT INTO product_run_transitions (id, run_id, attempt_id, workspace_id, sequence, to_state, "
            "end_reason, actor, recorded_at) VALUES ('t-1', 'r', 'a', 'w', 1, 'needs_approval', :reason, "
            "'runtime', '2026-10-01')"
        ),
        {"reason": END_REASON},
    )


def _forget_the_new_reason(connection: Connection) -> None:
    connection.execute(text("DELETE FROM product_run_transitions WHERE id = 't-1'"))
