"""Authored team conversation replies need the actual current hash-bound card."""
import pytest
from sqlalchemy import select

from app.models import WorkflowRunDecision
from app.services.workflow_runs.phase_turns import phased_turn_resolution
from tests.test_team_role_decider_callers import ready

pytestmark = pytest.mark.asyncio

async def test_authored_chat_text_cannot_answer_an_unconfirmed_current_question(db):
    case, _role = await ready(db, kind="user_conversation")
    before = dict(case.run.node_state)
    resolution = await phased_turn_resolution(db, case.run, user_message="an unbound answer",
                                               user=case.pm)
    assert case.run.status == "waiting" and case.run.node_state == before
    assert "card" in str(resolution)
    assert not (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == case.run.id))).scalars().all()
