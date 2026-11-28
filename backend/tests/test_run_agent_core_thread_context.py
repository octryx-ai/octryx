"""run_agent persists structured thread context, traces the workflow routing policy resolution and the admin chat bootstrap includes the selected thread."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, ThreadContext, User
from tests.conftest import ADMIN_PASSWORD
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


@pytest.mark.asyncio
async def test_admin_chat_bootstrap_includes_selected_thread_context(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.flush()
    db.add(
        ThreadContext(
            id=str(uuid.uuid4()),
            session_id=session.id,
            version=3,
            derived_from_message_id=None,
            context_json={
                "goal": "Investigate the latest Jira ticket",
                "current_task": "Check current ticket state",
                "constraints": ["Agent mode: diagnosis"],
                "open_questions": [],
                "active_entities": {"domains": ["jira"]},
                "current_repo_state": {},
                "current_ticket_state": {},
                "last_known_errors": [],
                "next_expected_action": "Continue with the next step based on the latest tool results.",
            },
        )
    )
    await db.commit()

    resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["selectedThreadContext"] is not None
    assert payload["selectedThreadContext"]["version"] == 3
    assert payload["selectedThreadContext"]["context"]["goal"] == "Investigate the latest Jira ticket"
