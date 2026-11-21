"""A device phase's last answer reaches the run (otherwise a device run's readiness questions stay only in the
chat; ``context.answers`` stays empty and the decision card shows no text)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models import Message, Session
from app.services.workflow_runs.octryx.stop_answers import _last_answer
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user


@pytest.mark.asyncio
async def test_the_stop_message_wins_else_the_newest_assistant_message_of_the_phase(db):
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=workspace_id)
    db.add(session)
    await db.flush()
    start = datetime(2026, 11, 11, 14, 40)
    for minutes, role, text in ((-5, "assistant", "an earlier phase"), (1, "user", "Continue the run"),
                                (2, "assistant", "1. Servings: profile field or session default?")):
        db.add(Message(id=str(uuid.uuid4()), session_id=session.id, role=role, content=text,
                       created_at=start + timedelta(minutes=minutes)))
    await db.flush()

    assert await _last_answer(db, session.id, start, {}) == "1. Servings: profile field or session default?"
    assert await _last_answer(db, session.id, start, {"last_assistant_message": " Ready. "}) == "Ready."
    assert await _last_answer(db, session.id, start + timedelta(minutes=10), {}) == ""
