"""Both session entry paths start a turn through the same owner.

``/api/v1/sessions/{id}/messages`` (in the request) and ``/chat/api/send`` (background task)
prepare through ``services/session/turn_start`` and must hold the same start facts:

* the running turn is marked (``running`` / ``in_progress``, R1 owner) and registered;
* a second turn while it runs is refused (``turn_already_running``, 409);
* a persisted in-progress run without a live task is refused (``duplicate_text``, 409);
* stop cancels it through the same path (``turn_stop``): ``stopped`` / ``user_cancelled``;
* the chosen runtime target, thinking level and agent reach ``run_agent``.

Only the refusal body differs: ``/chat/api`` keeps its plain detail, ``/api/v1`` answers the
state as ``code``. ``run_agent`` is replaced at the one seam of both paths (``turn_runner``).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select

import app.services.session.turn_runner as turn_runner
from app.api.routes._sessions_turn_routes import api_refusal_http_exception
from app.models import AgentDefinition, ControlPlaneRuntimeTarget, Message, Project, User
from app.models import Session as ChatSession
from app.services.runtime_ownership.process_identity import current_process_id
from app.services.session.run_state import RUN_STATUS_IN_PROGRESS, set_session_run_state
from app.services.session.turn_refusals import REFUSAL_HTTP_STATUS, TurnRefusal, TurnRefusalState
from app.services.session.turn_tasks import CHAT_RUN_TASKS
from app.web._helpers.chat_turn_prepare import chat_refusal_http_exception

PROMPT = "What time is it?"
PATHS = ("api-v1", "chat-api")


@pytest.fixture
def agent_gate(monkeypatch):
    """``run_agent`` at the shared seam: records its arguments and waits for ``release``."""
    state: dict[str, Any] = {"calls": [], "started": asyncio.Event(), "release": asyncio.Event()}

    async def gated_run_agent(**kwargs):
        state["calls"].append(kwargs)
        state["started"].set()
        await state["release"].wait()
        return
        yield  # an async generator, like run_agent

    monkeypatch.setattr(turn_runner, "run_agent", gated_run_agent)
    return state


async def _session(db, **metadata) -> ChatSession:
    project = Project(name=f"turn-start-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = ChatSession(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat", status="active", metadata_={}
    )
    if metadata.get("run_in_progress"):
        set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
    db.add(session)
    await db.commit()
    return session


async def _send(client, path: str, session_id: str, headers, **fields):
    if path == "api-v1":
        body = {"content": PROMPT, **fields}
        return await client.post(f"/api/v1/sessions/{session_id}/messages", json=body, headers=headers)
    body = {"prompt": PROMPT, "session_id": session_id, **fields}
    return await client.post("/chat/api/send", json=body, headers=headers)


async def _start_blocked_turn(client, path: str, session_id: str, headers, gate) -> asyncio.Task | None:
    """Start a turn that waits in ``run_agent``; ``/api/v1``'s request is returned as a task."""
    request = None
    if path == "api-v1":
        request = asyncio.create_task(_send(client, path, session_id, headers))
    else:
        assert (await _send(client, path, session_id, headers)).status_code == 200
    await asyncio.wait_for(gate["started"].wait(), timeout=30)
    return request


def _refusal_state(path: str, response) -> str:
    detail = response.json().get("detail")
    return detail["code"] if path == "api-v1" else detail


async def _finish(request: asyncio.Task | None, session_id: str):
    if request is not None:
        return await asyncio.wait_for(request, timeout=30)
    task = CHAT_RUN_TASKS.get(session_id)
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=30)
    return None


@pytest.mark.asyncio
@pytest.mark.committed_db
@pytest.mark.parametrize("path", PATHS)
async def test_a_running_turn_is_marked_owned_and_refuses_a_second_turn(client, db, auth_headers, agent_gate, path):
    session_id = (await _session(db)).id
    request = await _start_blocked_turn(client, path, session_id, auth_headers, agent_gate)

    db.expire_all()
    running = await db.get(ChatSession, session_id)
    assert running.status == "running"
    assert running.metadata_["run_status"] == RUN_STATUS_IN_PROGRESS
    assert running.turn_owner_process_id == current_process_id()
    assert not CHAT_RUN_TASKS[session_id].done()

    second = await _send(client, path, session_id, auth_headers)
    assert second.status_code == 409
    expected = "turn_already_running" if path == "api-v1" else "This thread is already running"
    assert _refusal_state(path, second) == expected

    agent_gate["release"].set()
    finished = await _finish(request, session_id)
    assert finished is None or finished.status_code == 200
    assert session_id not in CHAT_RUN_TASKS
    user_turns = await db.execute(select(Message).where(Message.session_id == session_id, Message.role == "user"))
    assert len(user_turns.scalars().all()) == 1


@pytest.mark.asyncio
@pytest.mark.committed_db
@pytest.mark.parametrize("path", PATHS)
async def test_a_persisted_in_progress_run_is_refused_as_duplicate_text(client, db, auth_headers, agent_gate, path):
    # The run is in progress on the row, but no task of this process runs it (another process owns it).
    session = await _session(db, run_in_progress=True)

    response = await _send(client, path, session.id, auth_headers)

    assert response.status_code == 409
    expected = "duplicate_text" if path == "api-v1" else "A turn of this thread is still in progress"
    assert _refusal_state(path, response) == expected
    assert agent_gate["calls"] == []


@pytest.mark.asyncio
@pytest.mark.committed_db
@pytest.mark.parametrize("path", PATHS)
async def test_stop_cancels_the_running_turn_through_the_same_path(client, db, auth_headers, agent_gate, path):
    session_id = (await _session(db)).id
    request = await _start_blocked_turn(client, path, session_id, auth_headers, agent_gate)

    stop_url = f"/api/v1/sessions/{session_id}/stop" if path == "api-v1" else f"/chat/api/sessions/{session_id}/stop"
    stopped = await client.post(stop_url, headers=auth_headers)
    assert stopped.status_code == 200, stopped.text

    finished = await _finish(request, session_id)
    if finished is not None:
        # The waiting /api/v1 request answers with the turn's messages, ending in the stop message.
        assert finished.status_code == 200, finished.text
        assert finished.json()[-1]["content"] == "Generation stopped by user."
    db.expire_all()
    row = await db.get(ChatSession, session_id)
    assert (row.metadata_["run_status"], row.metadata_["run_completion_reason"]) == ("stopped", "user_cancelled")
    assert row.status == "active"
    assert session_id not in CHAT_RUN_TASKS
    assert "current_turn_user_message_id" not in row.metadata_


@pytest.mark.asyncio
@pytest.mark.committed_db
@pytest.mark.parametrize("path", PATHS)
async def test_runtime_thinking_level_and_agent_reach_run_agent(client, db, auth_headers, agent_gate, path):
    session = await _session(db)
    target = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=session.user_id,
        name=f"Start Contract Agent {uuid.uuid4().hex[:6]}",
        goal="Answer the time",
        agent_type="chat",
        is_active=True,
    )
    db.add(agent)
    await db.commit()
    agent_gate["release"].set()

    response = await _send(
        client, path, session.id, auth_headers, runtime_target_id=target.id, thinking_level="deep", agent_id=agent.id
    )
    assert response.status_code == 200, response.text
    await _finish(None, session.id)

    call = agent_gate["calls"][0]
    assert call["runtime_target_id"] == target.id
    assert call["thinking_level"] == "deep"
    assert (call["agent_definition"] or {}).get("name") == agent.name


@pytest.mark.asyncio
@pytest.mark.committed_db
@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    ("fields", "state", "status"),
    [
        ({"runtime_target_id": "no-such-runtime"}, "runtime_target_invalid", 400),
        ({"agent_id": "no-such-agent"}, "agent_not_found", 404),
    ],
)
async def test_the_same_refusal_on_both_paths(client, db, auth_headers, agent_gate, path, fields, state, status):
    session = await _session(db)

    response = await _send(client, path, session.id, auth_headers, **fields)

    assert response.status_code == status
    if path == "api-v1":
        assert response.json()["detail"]["code"] == state
    assert agent_gate["calls"] == []


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_api_refuses_an_unknown_or_archived_session(client, db, auth_headers, agent_gate):
    unknown = await client.post(f"/api/v1/sessions/{uuid.uuid4()}/messages", json={"content": PROMPT}, headers=auth_headers)
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "session_not_found")

    session = await _session(db)
    session.status = "archived"
    await db.commit()
    archived = await _send(client, "api-v1", session.id, auth_headers)
    assert (archived.status_code, archived.json()["detail"]["code"]) == (409, "session_archived")


@pytest.mark.parametrize("state", list(TurnRefusalState))
def test_each_refusal_state_maps_to_one_status_on_both_adapters(state):
    refusal = TurnRefusal(state=state, detail="operator detail")

    chat = chat_refusal_http_exception(refusal)
    api = api_refusal_http_exception(refusal)

    assert chat.status_code == api.status_code == REFUSAL_HTTP_STATUS[state]
    assert chat.detail == "operator detail"
    assert api.detail == {"code": state.value, "detail": "operator detail"}
