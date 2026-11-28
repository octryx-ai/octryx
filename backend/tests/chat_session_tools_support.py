"""Shared helpers for the test_chat_session_tools_* modules."""

from __future__ import annotations

import pytest

from app.tools.context import ToolContext

CHAT_STATE = {"class": "read_only", "enforced": True, "source": "chat_default", "escalation_decision": None,
              "chat_connector_writes": True}


ACTIVE = {"jira_url": "https://jira.example.test", "confluence_url": "https://wiki.example.test",
          "k8s_api_url": "https://k8s.example.test", "k8s_token": "t",
          "servicenow_url": "https://sn.example.test", "servicenow_username": "u", "servicenow_password": "p"}


@pytest.fixture
async def chat_context(db):
    from sqlalchemy import select

    from app.models import Session as AgentSession
    from app.models import User

    user = (await db.execute(select(User))).scalars().first()
    session = AgentSession(id="chat-client-parity-session", user_id=user.id, agent_type="chat", status="active")
    db.add(session)
    await db.flush()
    return user, ToolContext(user_id=user.id, project_ids=[], roles=["member"], session_id=session.id,
                             project_config={}, db=db, agent_mode_key="diagnosis", capability_type="diagnosis",
                             run_capability=dict(CHAT_STATE))


async def _confirmed_again(db, user_id: str, held: dict, name: str, params: dict, context):
    from app.models import Session as AgentSession
    from app.services.approval.resolution_service import resolve_approval_request
    from app.tools.registry import execute_tool

    # The first write of a request proposes the plan; a later one outside it amends it.
    assert held.get("code") in {"write_plan_required", "write_plan_amendment_required"}, held
    assert held["plan_write"]["tool"] == name, held
    session = await db.get(AgentSession, context.session_id)
    if not (session.metadata_ or {}).get("current_turn_user_message_id"):
        session.metadata_ = {**(session.metadata_ or {}), "current_turn_user_message_id": f"request-{name}"}
        await db.flush()
    plan = await execute_tool("propose_write_plan", {"request": name, "writes": [held["plan_write"]]}, context)
    assert plan.get("approval_required") is True, plan
    await resolve_approval_request(db, approval_id=plan["approval_id"], resolved_by=user_id, status="approved")
    return await execute_tool(name, params, context)
