"""Tests for document updater sending, stale session, feedback, and message pagination."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

import app.web.routers.chat_sessions_threads as chat_session_threads_module
from app.agent.engine import (
    AgentEvent,
)
from app.models import AgentDefinition, Message, Session, User
from app.services.session import turn_runner
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_send_uses_seeded_document_updater_definition_from_db(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    agent = (await db.execute(select(AgentDefinition).where(AgentDefinition.name == "Document Updater"))).scalar_one()

    observed = {}

    async def fake_run_agent(
        *,
        session_id,
        user_message,
        user_id,
        project_id,
        agent_type,
        db,
        runtime_target_id=None,
        thinking_level=None,
        agent_definition=None,
        run_origin=None,
    ):
        observed["agent_type"] = agent_type
        observed["thinking_level"] = thinking_level
        observed["agent_definition"] = agent_definition
        await asyncio.sleep(0.05)
        assistant_message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content="Seeded document updater run completed.",
            model="stepfun/step-3.5-flash:free",
        )
        db.add(assistant_message)
        await db.commit()
        yield AgentEvent(role="assistant", content="Seeded document updater run completed.")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={
            "prompt": "Pruefe die letzten report-builder-Aenderungen und bewerte den Doku-Bedarf.",
            "agent_id": agent.id,
        },
    )
    assert send_resp.status_code == 200
    payload = send_resp.json()
    assert payload["selectedAgentId"] == agent.id
    assert payload["selectedAgentName"] == "Document Updater"
    assert payload["selectedSession"]["status"] == "running"
    for _ in range(20):
        if "agent_type" in observed:
            break
        await asyncio.sleep(0.05)

    assert observed["agent_type"] == "change"
    assert observed["thinking_level"] == "deep"
    assert observed["agent_definition"]["name"] == "Document Updater"
    assert observed["agent_definition"]["branchPrefix"] == "octryx"
    assert [step["name"] for step in observed["agent_definition"]["steps"]] == [
        "Collect changes",
        "Derive documentation needs",
        "Update Confluence",
    ]
    assert observed["agent_definition"]["steps"][0]["allowedTools"] == [
        "list_recent_bitbucket_commits",
        "search_jira_tickets",
        "prepare_bitbucket_repository",
        "git_change_summary",
        "list_workspace_git_commits",
        "analyze_workspace_repository",
    ]
    assert observed["agent_definition"]["steps"][1]["allowedTools"] == [
        "knowledge_search",
        "search_confluence",
        "list_confluence_pages",
        "get_confluence_page",
    ]
    assert observed["agent_definition"]["steps"][2]["allowedTools"] == [
        "list_confluence_pages",
        "get_confluence_page",
        "update_confluence_page",
        "create_confluence_page",
    ]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_continue_allows_stale_running_session_without_live_worker(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        agent_type="diagnosis",
        status="running",
        metadata_={"title": "Stale running thread"},
    )
    db.add(session)
    await db.commit()

    observed = {}

    async def fake_run_agent(*, session_id, user_message, **kwargs):
        observed["session_id"] = session_id
        observed["user_message"] = user_message
        yield AgentEvent(role="assistant", content="continued")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    continue_resp = await client.post(f"/admin/chat/api/sessions/{session.id}/continue", json={})
    assert continue_resp.status_code == 200
    assert continue_resp.json()["selectedSession"]["id"] == session.id
    for _ in range(20):
        if "session_id" in observed:
            break
        await asyncio.sleep(0.05)

    assert observed["session_id"] == session.id
    assert "Do not restart from scratch" in observed["user_message"]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_continue_passes_explicit_runtime_override_to_turn_start(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        agent_type="chat",
        status="active",
        metadata_={
            "title": "Runtime override thread",
            "runtime_target_id": "old-runtime",
            "thinking_level": "light",
        },
    )
    db.add(session)
    await db.commit()

    captured: dict[str, object] = {}

    async def fake_start_chat_turn(**kwargs):
        captured.update(kwargs)
        return session

    async def fake_build_chat_turn_ack_state(*_args, **kwargs):
        return {
            "selectedSession": {"id": session.id},
            "selectedRuntimeTargetId": kwargs["runtime_target_id"],
            "selectedThinkingLevel": kwargs["thinking_level"],
        }

    monkeypatch.setattr(chat_session_threads_module, "_start_chat_turn", fake_start_chat_turn)
    monkeypatch.setattr(chat_session_threads_module, "_build_chat_turn_ack_state", fake_build_chat_turn_ack_state)

    continue_resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/continue",
        json={
            "runtime_target_id": "new-runtime",
            "thinking_level": "deep",
        },
    )

    assert continue_resp.status_code == 200
    assert captured["runtime_target_id"] == "new-runtime"
    assert captured["runtime_target_id_explicit"] is True
    assert captured["thinking_level"] == "deep"
    assert captured["thinking_level_explicit"] is True
    assert continue_resp.json()["selectedRuntimeTargetId"] == "new-runtime"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_turn_exception_resets_session_to_active(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    async def failing_run_agent(**kwargs):
        raise RuntimeError("synthetic failure")
        yield  # pragma: no cover

    monkeypatch.setattr(turn_runner, "run_agent", failing_run_agent)

    send_resp = await client.post("/admin/chat/api/send", json={"prompt": "Trigger failure"})
    assert send_resp.status_code == 200
    payload = send_resp.json()
    session_id = payload["selectedSession"]["id"]

    final_payload = payload
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assert final_payload["selectedSessionIsRunning"] is False
    assert final_payload["selectedSession"]["status"] == "active"
    assert final_payload["selectedSession"]["runStatus"] == "failed"
    assert final_payload["selectedSession"]["runCompletionReason"] == "error"
    await db.rollback()
    session = await db.get(Session, session_id)
    assert session is not None
    assert session.status == "active"
    messages = (
        (await db.execute(select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())))
        .scalars()
        .all()
    )
    error_contents = [m.content or "" for m in messages if (m.content or "").startswith("Agent error:")]
    assert any("agent_run_failed error_type=RuntimeError" in content for content in error_contents)
    assert not any("synthetic failure" in content for content in error_contents)
