"""A chat's write plan: the chat's tool context (``chat``) and recorded connector writes (``writes``)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Session as AgentSession
from app.models import User
from app.tools.context import ToolContext
from app.tools.registry import TOOL_REGISTRY

JIRA = {"jira_url": "https://jira.example.test"}
CHAT_STATE = {"class": "read_only", "enforced": True, "source": "chat_default", "escalation_decision": None,
              "chat_connector_writes": True}


@pytest.fixture
async def chat(db):
    user = (await db.execute(select(User))).scalars().first()
    session = AgentSession(id="chat-write-plan-session", user_id=user.id, agent_type="chat", status="active",
                           metadata_={"current_turn_user_message_id": "request-1"})
    db.add(session)
    await db.flush()
    context = ToolContext(user_id=user.id, project_ids=[], roles=["member"], session_id=session.id,
                          project_config=dict(JIRA), db=db, agent_mode_key="diagnosis", capability_type="diagnosis",
                          run_capability=dict(CHAT_STATE))
    return user, session, context


@pytest.fixture
def writes(monkeypatch):
    """Recorded writes instead of HTTP: Jira tickets get CHEF-<n>, work items OE-<n>."""
    calls: list[tuple[str, dict]] = []

    def recorder(tool_name, result):
        async def execute(params, context):
            calls.append((tool_name, dict(params)))
            return result(len(calls)) if callable(result) else result
        return execute

    monkeypatch.setattr(TOOL_REGISTRY["create_jira_ticket"], "execute",
                        recorder("create_jira_ticket", lambda n: {"key": f"CHEF-{n}"}))
    monkeypatch.setattr(TOOL_REGISTRY["add_jira_comment"], "execute", recorder("add_jira_comment", {"ok": True}))
    monkeypatch.setattr(TOOL_REGISTRY["work_item_create"], "execute",
                        recorder("work_item_create", {"id": "wi-7", "source_key": "OCX-7"}))
    monkeypatch.setattr(TOOL_REGISTRY["work_item_note"], "execute", recorder("work_item_note", {"ok": True}))
    return calls
