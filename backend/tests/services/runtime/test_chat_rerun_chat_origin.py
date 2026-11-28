"""A chat rerun is a chat entry point, so its run has a profile origin."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Message, Session, User
from app.services.chat_rerun import prepare_chat_rerun
from app.services.run_capability.resolution import (
    RUN_CAPABILITY_STATUS_ALLOWED,
    SOURCE_CHAT_DEFAULT,
    decide_run_capability,
)
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.time_utils import utc_now

KEY = ROUTING_RESOLUTION_KEY


async def _thread(db, metadata: dict) -> tuple[Session, Message]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active",
                      metadata_=metadata)
    db.add(session)
    await db.flush()
    at = utc_now() - timedelta(minutes=1)
    user = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="create test.txt", created_at=at)
    answer = Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content="old",
                     created_at=at + timedelta(seconds=1))
    db.add_all([user, answer])
    await db.flush()
    return session, answer


@pytest.mark.asyncio
async def test_a_rerun_without_a_recorded_routing_resolution_runs_as_a_chat_turn(db):
    session, answer = await _thread(db, {"title": "t"})

    prepared = await prepare_chat_rerun(db, session=session, target_message=answer, prompt="create test.txt")

    resolution = prepared.session.metadata_[KEY]
    assert isinstance(resolution, dict) and resolution["status"] == "unmatched" and resolution["workflow_id"] is None
    decided = decide_run_capability(routing_resolution=resolution, requested_agent_type="diagnosis",
                                    requested_mode_capability="diagnosis")
    assert (decided.status, decided.source) == (RUN_CAPABILITY_STATUS_ALLOWED, SOURCE_CHAT_DEFAULT)
    # Without it the same run has no origin and the gate refuses it.
    missing = decide_run_capability(routing_resolution=None, requested_agent_type="diagnosis",
                                    requested_mode_capability="diagnosis")
    assert missing.source == "missing_declaration"


@pytest.mark.asyncio
async def test_a_rerun_keeps_the_routing_resolution_its_thread_recorded(db):
    recorded = {"source": "db", "status": "matched", "workflow_id": "wf-1"}
    session, answer = await _thread(db, {"title": "t", KEY: recorded})

    prepared = await prepare_chat_rerun(db, session=session, target_message=answer, prompt="create test.txt")

    assert prepared.session.metadata_[KEY] == recorded


def test_a_run_without_an_origin_answers_in_plain_words_and_keeps_the_reason_internal():
    capability = decide_run_capability(routing_resolution=None, requested_agent_type="diagnosis",
                                       requested_mode_capability="diagnosis")
    profile = {"status": capability.status, "reason": capability.reason, "capability": capability.to_metadata()}

    gate = evaluate_execution_gate(profile)

    assert not gate.allowed and gate.status == "needs_configuration"
    for jargon in ("profile origin", "declare its origin", "routing resolution", "Reason:"):
        assert jargon not in gate.user_message
    assert "Send it again" in gate.user_message
    assert "no profile origin" in gate.reason and "no profile origin" in gate.trace_output()["reason"]


def test_other_configuration_gates_keep_their_reason():
    gate = evaluate_execution_gate({"status": "needs_configuration", "reason": "No model runtime is set up.",
                                    "capability": {"source": "chat_default"}})
    assert gate.user_message.endswith("Reason: No model runtime is set up.")
