"""An inactive Agent Definition starts no new execution.

The live ``is_active`` switch is checked by the shared resolver after ownership and before any
content is built, so every consumer answers the same typed refusal: chat turns from every
selection source, both send routes, rerun, background steps and Flow agent steps. Another owner's
agent stays ``Agent not found``. Nothing falls back to a plain turn or another agent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

import app.services.session.turn_runner as turn_runner
from app.models import Message, Project, User
from app.models import Session as ChatSession
from app.scheduler.execution._step_agent_loader import load_agent_for_step
from app.services.agent_definition_execution import resolve_agent_definition_for_execution
from app.services.agent_definition_execution_outcomes import (
    AgentDefinitionExecutionError,
    require_execution_payload,
)
from app.services.agent_definition_execution_states import (
    AGENT_DEFINITION_EXECUTION_MODE_KEY,
    INACTIVE_ERROR_CODE,
    SOURCE_PUBLISHED_REVISION,
    STATUS_INACTIVE,
)
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision
from app.services.agent_definition_snapshot import snapshot_header
from app.services.flow_orchestration.flow_agent_reference import (
    AGENT_INACTIVE,
    FlowAgentReferenceError,
    flow_agent_reference_errors,
)
from app.services.flow_orchestration.flow_agent_step import _resolve as resolve_flow_agent
from app.services.session.agent_selection_sources import AgentSelectionSource
from app.services.system_config.values import set_system_config_value
from app.time_utils import utc_now
from tests.agent_definition_revision_fixtures import DEFINITION_GOAL, admin_user, make_definition
from tests.turn_agent_selection_support import _workspace
from tests.turn_preparation_support import prepare_chat_turn

INACTIVE_MESSAGE = "This agent is inactive, so it cannot start new turns. Activate it on its agent page to use it again."


def _refusal(definition_id: str) -> dict:
    return {"code": INACTIVE_ERROR_CODE, "message": INACTIVE_MESSAGE, "definition_id": definition_id}


async def _definition(db, mode: str, *, project_id: str | None = None):
    owner = await admin_user(db)
    definition = await make_definition(db, owner=owner, project_id=project_id, steps=1)
    if mode == "published":
        # Published while active: the snapshot records an active definition.
        revision = await create_draft_revision(db, definition=definition, created_by=owner.id)
        await publish_revision(db, revision=revision, published_by=owner.id)
        assert snapshot_header(revision.snapshot)["is_active"] is True
    await set_system_config_value(db, key=AGENT_DEFINITION_EXECUTION_MODE_KEY, value=mode, description="test")
    return owner, definition


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["draft", "published"])
async def test_the_live_switch_refuses_without_building_content_and_reactivation_restores(db, mode):
    owner, definition = await _definition(db, mode)
    definition.is_active = False
    await db.flush()

    resolution = await resolve_agent_definition_for_execution(db, definition_id=definition.id, visible_to_user_id=owner.id)
    assert (resolution.status, resolution.payload, resolution.revision_id) == (STATUS_INACTIVE, None, None)
    with pytest.raises(HTTPException) as refused:
        require_execution_payload(resolution)
    assert refused.value.status_code == 409
    assert refused.value.detail == _refusal(definition.id)

    definition.is_active = True
    await db.flush()
    restored = await resolve_agent_definition_for_execution(db, definition_id=definition.id, visible_to_user_id=owner.id)
    assert restored.resolved and restored.payload["goal"] == DEFINITION_GOAL
    if mode == "published":
        assert restored.source == SOURCE_PUBLISHED_REVISION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        AgentSelectionSource.EXPLICIT,
        AgentSelectionSource.MENTION,
        AgentSelectionSource.SESSION,
        AgentSelectionSource.DEFAULT,
    ],
)
async def test_every_selection_source_refuses_an_inactive_agent_instead_of_falling_back(db, source):
    ws = await _workspace(db, default_agent=True)
    inactive = ws.agents[source.value]
    inactive.is_active = False
    await db.commit()

    with pytest.raises(HTTPException) as refused:
        await prepare_chat_turn(
            db=db,
            user=ws.admin,
            prompt=f"@{inactive.name} continue" if source == AgentSelectionSource.MENTION else "Continue.",
            project_id=ws.project.id,
            session_id=ws.session.id if source == AgentSelectionSource.SESSION else "",
            agent_id=inactive.id if source == AgentSelectionSource.EXPLICIT else "",
        )
    assert refused.value.status_code == 409
    assert refused.value.detail == _refusal(inactive.id)


@pytest.fixture
def run_agent_calls(monkeypatch):
    """``run_agent`` at the shared turn seam: records each launch and answers at once."""
    calls: list[dict] = []

    async def recording_run_agent(**kwargs):
        calls.append(kwargs)
        return
        yield  # an async generator, like run_agent

    monkeypatch.setattr(turn_runner, "run_agent", recording_run_agent)
    return calls


async def _bound_chat(db, *, active: bool) -> tuple[ChatSession, str]:
    """An existing Chat bound to an agent, with one earlier exchange."""
    owner = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"inactive-agent-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    definition = await make_definition(db, owner=owner, project_id=project.id, steps=0)
    definition.is_active = active
    session = ChatSession(
        id=str(uuid.uuid4()), user_id=owner.id, project_id=project.id, agent_type="diagnosis", status="active",
        metadata_={"agent_definition_id": definition.id, "bound_agent_definition_id": definition.id,
                   "thinking_level": "light", "runtime_target_id": ""},
    )
    db.add(session)
    started = utc_now() - timedelta(minutes=5)
    db.add_all([
        Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="First", created_at=started),
        Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content="Answer",
                created_at=started + timedelta(seconds=5)),
    ])
    await db.commit()
    return session, definition.id


async def _message_count(db, session_id: str) -> int:
    return (await db.execute(select(func.count()).select_from(Message).where(Message.session_id == session_id))).scalar()


@pytest.mark.asyncio
@pytest.mark.committed_db
@pytest.mark.parametrize("path", ["api-v1", "chat-api"])
async def test_a_continued_chat_with_an_inactive_agent_launches_nothing(client, db, auth_headers, run_agent_calls, path):
    session, definition_id = await _bound_chat(db, active=False)
    session_id = session.id

    if path == "api-v1":
        response = await client.post(
            f"/api/v1/sessions/{session.id}/messages", json={"content": "Add 2 and 4."}, headers=auth_headers
        )
        assert response.json()["detail"] == {"code": "agent_definition_refused", "detail": _refusal(definition_id)}
    else:
        response = await client.post(
            "/chat/api/send",
            json={"prompt": "Add 2 and 4.", "session_id": session.id},
            headers=auth_headers,
        )
        assert response.json()["detail"] == _refusal(definition_id)

    assert response.status_code == 409
    assert run_agent_calls == []
    db.expire_all()
    assert await _message_count(db, session_id) == 2
    assert (await db.get(ChatSession, session_id)).status == "active"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_the_active_counterpart_still_runs_with_its_agent(client, db, auth_headers, run_agent_calls):
    session, definition_id = await _bound_chat(db, active=True)
    response = await client.post(
        f"/api/v1/sessions/{session.id}/messages", json={"content": "Add 2 and 4."}, headers=auth_headers
    )
    assert response.status_code == 200
    assert [call["agent_definition"]["id"] for call in run_agent_calls] == [definition_id]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_rerun_with_an_inactive_agent_refuses_before_rewinding(client, db, auth_headers, run_agent_calls):
    session, definition_id = await _bound_chat(db, active=False)
    session_id = session.id
    first_user = (
        await db.execute(select(Message).where(Message.session_id == session.id, Message.role == "user"))
    ).scalar_one()
    first_user_id = first_user.id

    response = await client.post(
        f"/chat/api/sessions/{session_id}/messages/{first_user_id}/rerun",
        json={"prompt": "Edited first"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == _refusal(definition_id)
    assert run_agent_calls == []
    db.expire_all()
    assert await _message_count(db, session_id) == 2, "the later answer is not deleted"
    assert (await db.get(Message, first_user_id)).content == "First"
    assert (await db.get(ChatSession, session_id)).status == "active"


@pytest.mark.asyncio
async def test_a_background_step_fails_typed_instead_of_running_without_its_agent(db):
    _, definition = await _definition(db, "draft")
    definition.is_active = False
    await db.flush()
    step = SimpleNamespace(connector_params={}, runtime_selector={})
    task = SimpleNamespace(config={"agent_definition_id": definition.id})

    with pytest.raises(AgentDefinitionExecutionError) as refused:
        await load_agent_for_step(step, task, db, logging.getLogger(__name__))
    assert refused.value.code == INACTIVE_ERROR_CODE
    assert refused.value.as_metadata()["status"] == STATUS_INACTIVE
    assert DEFINITION_GOAL not in str(refused.value.as_metadata())


@pytest.mark.asyncio
async def test_a_flow_agent_step_keeps_the_typed_agent_inactive_result(db):
    owner, definition = await _definition(db, "draft")
    definition.is_active = False
    await db.flush()

    with pytest.raises(FlowAgentReferenceError) as refused:
        await resolve_flow_agent(db, definition.id, owner.id)
    assert refused.value.code == AGENT_INACTIVE
    node = {"id": "n1", "type": "agent_step", "config": {"agent_definition_id": definition.id}}
    errors = await flow_agent_reference_errors(db, {"nodes": [node]}, user_id=owner.id, project_id=None)
    assert [error["code"] for error in errors] == [AGENT_INACTIVE]
