"""run_agent persists structured thread context, traces the workflow routing policy resolution and the admin chat bootstrap includes the selected thread."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    run_agent,
)
from app.models import Session, ThreadContext, TurnTrace, User
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.conftest import ADMIN_PASSWORD
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


@pytest.mark.asyncio
async def test_run_agent_persists_structured_thread_context(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return (
            {
                "content": "I will summarize the latest Jira and Bitbucket activity next.",
                "tool_calls": None,
                "model": "claude-haiku-4.5",
                "usage": {"prompt_tokens": 15, "completion_tokens": 5, "total_tokens": 20},
            },
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    async for _event in run_agent(
        session_id=session.id,
        user_message="Create a daily summary from Jira and Bitbucket for today.",
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        db=db,
    ):
        continue

    thread_context = (
        await db.execute(select(ThreadContext).where(ThreadContext.session_id == session.id))
    ).scalar_one_or_none()
    assert thread_context is not None
    assert thread_context.version >= 1
    assert thread_context.context_json["goal"] == "Create a daily summary from Jira and Bitbucket for today."
    assert thread_context.context_json["current_task"] == "Create a daily summary from Jira and Bitbucket for today."
    # Domains come from the explicit context plan only; the prompt's "Jira and Bitbucket" adds none.
    assert "domains" not in thread_context.context_json.get("active_entities", {})
    assert (
        thread_context.context_json["next_expected_action"] == "Continue the thread from the latest assistant response."
    )


@pytest.mark.asyncio
async def test_run_agent_trace_includes_the_workflow_run_phase_resolution(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    routing_resolution = {
        "source": "db",
        "status": "matched",
        "selection_source": "workflow_run",
        "workflow_key": "incident-analysis",
        "workflow_id": "knowledge_request",
        "workflow_class": "knowledge_request",
        "policy_id": None,
        "policy_version_id": None,
        "matched_group_id": None,
        "workflow_contract": {"workflow_id": "knowledge_request", "workflow_class": "knowledge_request",
                              "capability_class": "read_only"},
        "tool_policy": {"allowlist": ["knowledge_search", "knowledge_read"], "denylist": []},
        "safety_constraints": {"diagnosis_mode": True, "allow_mutating_tools": False},
    }
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="running",
        metadata_={ROUTING_RESOLUTION_KEY: routing_resolution},
    )
    db.add(session)
    await db.commit()

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return (
            {
                "content": "Here is what the knowledge base says about the release process.",
                "tool_calls": None,
                "model": "claude-haiku-4.5",
                "usage": {"prompt_tokens": 15, "completion_tokens": 7, "total_tokens": 22},
            },
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    async for _event in run_agent(
        session_id=session.id,
        user_message="What do we know about the release process?",
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        db=db,
    ):
        continue

    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all()
    assert traces
    trace = next(
        item
        for item in traces
        if (item.context_snapshot_json or {}).get("request_analysis", {}).get(
            ROUTING_RESOLUTION_KEY
        )
    )
    context = trace.context_snapshot_json
    assert context["request_analysis"][ROUTING_RESOLUTION_KEY] == routing_resolution
    workflow_contract = context["request_analysis"]["workflow_contract"]
    assert workflow_contract["workflow_id"] == "knowledge_request"
    assert workflow_contract["workflow_class"] == "knowledge_request"
    routing_events = [
        event for event in context["decision_timeline"] if event.get("phase") == "routing_policy"
    ]
    assert len(routing_events) == 1
    assert routing_events[0]["title"] == "Workflow run phase selected"
    assert routing_events[0]["metadata"]["workflow_class"] == "knowledge_request"
    assert routing_events[0]["metadata"]["allowed_tools"] == ["knowledge_read", "knowledge_search"]


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
