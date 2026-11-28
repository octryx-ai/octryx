"""Which trace decides an Action run's verdict: only the run's single latest finished final after the boundary counts, and a later user message disqualifies the run."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import Message
from app.services.session.turn_final_outcome import (
    TurnFinalOutcome,
    action_reply_verdict,
    capture_trace_boundary,
    load_run_final_outcome,
)
from app.time_utils import utc_now
from tests.scheduler.test_action_runtime_admission import _admin
from tests.support.agent_reply_contract_runtime_actions_support import (
    FINISHED_SATISFIED,
    INTERMEDIATE,
    NOT_JSON,
    SATISFIED,
    STOPPED_NOT_JSON,
    UNCHECKED,
    _foreign_chat_turn,
    _session,
    _trace,
    _write_run,
)


def _final(outcome, *, stop_reason=None, record=None):
    return TurnFinalOutcome(trace_id="t", outcome=outcome, stop_reason=stop_reason, reply_contract=record)


@pytest.mark.parametrize(("final", "verdict"), [
    (_final("finished", record=SATISFIED), None),
    (_final("stopped", stop_reason="agent_reply_not_json", record=NOT_JSON), "agent_reply_not_json"),
    (_final("finished", record=NOT_JSON), "agent_reply_not_json"),
    (_final("stopped", stop_reason="agent_reply_schema_mismatch"), "agent_reply_schema_mismatch"),
    (_final("stopped", stop_reason="step_stalled"), UNCHECKED),
    (_final("finished"), UNCHECKED),
    (_final("failed", record=SATISFIED), UNCHECKED),
    (None, UNCHECKED),
])
def test_the_action_verdict_is_success_only_for_a_finished_satisfied_final(final, verdict):
    assert action_reply_verdict(final) == verdict


@pytest.mark.parametrize(("run", "expected"), [
    ([INTERMEDIATE, FINISHED_SATISFIED], "finished"),
    ([], None),  # e.g. the iteration-budget fallback writes an answer without any trace
    ([INTERMEDIATE], None),
    ([FINISHED_SATISFIED, STOPPED_NOT_JSON], None),
    ([FINISHED_SATISFIED, INTERMEDIATE], None),
])
async def test_only_the_runs_single_latest_final_after_the_boundary_counts(db, run, expected):
    owner = await _admin(db)
    session = await _session(db, owner.id)
    # A reused session: an earlier run's finished, satisfied final is already there.
    await _trace(db, session.id, at=utc_now() - timedelta(minutes=10), **FINISHED_SATISFIED)
    boundary = await capture_trace_boundary(db, session.id)

    ids = await _write_run(db, session.id, run)

    final = await load_run_final_outcome(db, session.id, boundary)
    if expected is None:
        assert final is None, "an older run's final never counts, nor zero, several or a non-latest final"
    else:
        assert (final.trace_id, final.outcome, final.reply_contract) == (ids[-1], expected, SATISFIED)


async def test_a_trace_at_the_boundary_timestamp_belongs_to_the_earlier_run(db):
    owner = await _admin(db)
    session = await _session(db, owner.id)
    at = utc_now()
    await _trace(db, session.id, at=at, **FINISHED_SATISFIED)
    boundary = await capture_trace_boundary(db, session.id)
    assert await load_run_final_outcome(db, session.id, boundary) is None
    newer = await _trace(db, session.id, at=at, **FINISHED_SATISFIED)  # same timestamp, new id
    assert (await load_run_final_outcome(db, session.id, boundary)).trace_id == newer


async def test_a_user_message_after_the_boundary_disqualifies_the_run(db):
    owner = await _admin(db)
    session = await _session(db, owner.id)
    db.add(Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="Earlier chat",
                   created_at=utc_now() - timedelta(minutes=5)))
    await db.flush()
    boundary = await capture_trace_boundary(db, session.id)
    assert (await _write_run(db, session.id, [FINISHED_SATISFIED])) and (
        await load_run_final_outcome(db, session.id, boundary)
    ) is not None, "an earlier user message does not disqualify the run"

    boundary = await capture_trace_boundary(db, session.id)
    await _foreign_chat_turn(db, session.id)
    assert await load_run_final_outcome(db, session.id, boundary) is None
