"""Chat send and bootstrap keep the explicit project, runtime, thinking and strategy choices without preselecting defaults."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.agent.engine import (
    AgentEvent,
)
from app.models import (
    AgentDefinition,
    ControlPlaneRuntimeTarget,
    Message,
    Project,
    Session,
    User,
)
from app.services.session import turn_runner
from tests.conftest import ADMIN_PASSWORD


def _build_legacy_document_updater(owner_id: str, runtime_target_id: str) -> AgentDefinition:
    return AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        # Global: a turn in the explicit Workspace never runs another Workspace's agent (review finding 1).
        project_id=None,
        name="Legacy Document Updater",
        description="Legacy document updater",
        goal="Update documentation",
        agent_type="change",
        runtime_target_id=runtime_target_id,
        thinking_level="deep",
        is_active=True,
    )


def _stub_run_agent_reply(monkeypatch) -> None:
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
    ):
        assistant_message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content="Explicit contract preserved.",
            model="gpt-5.3-codex",
        )
        db.add(assistant_message)
        await db.commit()
        yield AgentEvent(role="assistant", content="Explicit contract preserved.")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)


async def _bootstrap_until_idle(client, session_id: str, payload: dict) -> dict:
    final_payload = payload
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break
    return final_payload


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_preserves_explicit_project_runtime_thinking_and_agent_mode(client, db, monkeypatch):
    # The selected agent definition decides the mode; the chat request names no mode.
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    explicit_project = Project(id=str(uuid.uuid4()), name="explicit-chat-project", config={}, is_active=True)
    legacy_project = Project(id=str(uuid.uuid4()), name="legacy-chat-project", config={}, is_active=True)
    db.add_all([explicit_project, legacy_project])
    await db.flush()

    explicit_runtime_target = (
        await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.is_active.is_(True)))
    ).scalars().first()
    assert explicit_runtime_target is not None

    agent = _build_legacy_document_updater(admin_user.id, explicit_runtime_target.id)
    db.add(agent)
    await db.commit()

    _stub_run_agent_reply(monkeypatch)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={
            "prompt": "Create a concise research document.",
            "project_id": explicit_project.id,
            "runtime_target_id": explicit_runtime_target.id,
            "thinking_level": "light",
            "agent_id": agent.id,
        },
    )
    assert send_resp.status_code == 200
    payload = send_resp.json()

    assert payload["selectedProjectId"] == explicit_project.id
    assert payload["selectedRuntimeTargetId"] == explicit_runtime_target.id
    assert payload["selectedThinkingLevel"] == "light"
    assert payload["selectedSession"]["projectId"] == explicit_project.id
    assert payload["selectedSession"]["runtimeTargetId"] == explicit_runtime_target.id
    assert payload["selectedSession"]["agentType"] == "change"

    session_id = payload["selectedSession"]["id"]
    final_payload = await _bootstrap_until_idle(client, session_id, payload)

    assert final_payload["selectedSession"]["projectId"] == explicit_project.id
    assert final_payload["selectedSession"]["runtimeTargetId"] == explicit_runtime_target.id
    assert final_payload["selectedSession"]["agentType"] == "change"
    assert final_payload["selectedThinkingLevel"] == "light"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_keeps_neutral_strategy_for_research_prompt_without_selection(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

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
    ):
        assistant_message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content="Research workflow started.",
            model="gpt-5.3-codex",
        )
        db.add(assistant_message)
        await db.commit()
        yield AgentEvent(role="assistant", content="Research workflow started.")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={
            "prompt": (
                "Create a cited Word research document about ticketing API integration risks, benefits, "
                "use cases, and enterprise rollout guidance."
            ),
        },
    )
    assert send_resp.status_code == 200
    payload = send_resp.json()

    session_id = payload["selectedSession"]["id"]
    session = await db.get(Session, session_id)
    assert session is not None
    # Explicit-first: without a workflow selection the strategy stays neutral;
    # workflows are selected via workflow_key or the model-side catalog.
    assert (session.metadata_ or {}).get("execution_strategy") == "direct"
    assert (session.metadata_ or {}).get("execution_strategy_reason") == "strategy:direct_default"
    assert (session.metadata_ or {}).get("expected_workflow_id") is None


@pytest.mark.asyncio
async def test_chat_bootstrap_new_thread_does_not_preselect_project_defaults(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name="neutral-entrypoint-project",
        config={"project_agent_preferences": {}},
        is_active=True,
    )
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="Neutral Default Delivery Agent",
        description="Coordinates delivery work.",
        goal="Coordinate delivery work",
        agent_type="change",
        thinking_level="deep",
        is_active=True,
    )
    db.add_all([project, agent])
    await db.commit()

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?new=true&project_id={project.id}")

    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()
    assert payload["newThread"] is True
    assert payload["selectedProjectId"] == project.id
    assert payload["selectedAgentId"] == ""
    assert payload["selectedAgentName"] == ""
    assert payload["selectedAgentSelectionSource"] == ""
    assert payload["selectedAgentType"] == "diagnosis"
