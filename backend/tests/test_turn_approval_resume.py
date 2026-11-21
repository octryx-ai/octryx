"""A chat turn paused at an approval resumes the same way on both session paths.

``/api/v1/sessions/{id}/messages`` and ``/chat/api/send`` both start a turn; an
approval-required tool pauses it; ``/chat/api/approvals/{id}/approve`` resumes it
exactly once, as a Chat turn bound to a Product Run, and only for a user with
write access to the session.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
import app.agent.providers as providers_module
from app.models import Approval, Project, User
from app.models import Session as ChatSession
from app.models.runtime.product_run import ProductRun
from app.services.auth import create_access_token, hash_password
from app.services.chat_turn_background import drain_chat_turn_background_tasks
from app.services.session.turn_approval_state import PAUSED_TURNS_METADATA_KEY
from app.services.session.turn_tasks import CHAT_RUN_TASKS
from app.tools.definitions import get_all_definitions
from app.tools.registry import TOOL_REGISTRY

TOOL = "get_current_time"
PROMPT = "What time is it?"
TOOL_CALL = {"id": "call_1", "type": "function", "function": {"name": TOOL, "arguments": "{}"}}
TOOL_RESPONSE = {"content": "", "tool_calls": [TOOL_CALL], "usage": {"prompt_tokens": 11, "completion_tokens": 3}}
FINAL_RESPONSE = {"content": "It is midnight UTC.", "tool_calls": None, "usage": {"prompt_tokens": 7, "completion_tokens": 2}}
APPROVAL_POLICY = {"approval_policy": {"require_for_tools": [TOOL]}}


@pytest.fixture
def world(monkeypatch):
    """A scripted provider (no network) and one approval-governed tool that counts its executions."""
    state: dict[str, Any] = {"script": [], "executions": 0}

    async def fixed_time(params, context):
        state["executions"] += 1
        return {"utc_time_iso": "2026-09-30T00:00:00+00:00", "timezone_name": "UTC"}

    monkeypatch.setattr(TOOL_REGISTRY[TOOL], "execute", fixed_time)
    original_prepare = engine_module._prepare_agent_run

    async def prepare(**kwargs):
        prepared = await original_prepare(**kwargs)
        prepared.tool_definitions = [get_all_definitions()[TOOL]]
        prepared.tool_context.project_config = {**(prepared.tool_context.project_config or {}), **APPROVAL_POLICY}
        return prepared

    def provider_factory(**_kwargs):
        class _ScriptedProvider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                return {**state["script"].pop(0), "model": model or ""}

            async def close(self):
                return None

        return _ScriptedProvider()

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare)
    monkeypatch.setattr(providers_module, "get_provider", provider_factory)
    monkeypatch.setattr(engine_module, "get_provider", provider_factory)
    return state


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _active_session(db) -> ChatSession:
    project = Project(name=f"approval-resume-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    admin = await _admin(db)
    session = ChatSession(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat", status="active", metadata_={}
    )
    db.add(session)
    await db.commit()
    return session


async def _pending_approval(db, session_id: str) -> Approval:
    return (
        await db.execute(select(Approval).where(Approval.session_id == session_id, Approval.status == "pending"))
    ).scalar_one()


async def _start_api_turn(client, db, headers, world) -> ChatSession:
    session = await _active_session(db)
    world["script"] = [TOOL_RESPONSE]
    resp = await client.post(f"/api/v1/sessions/{session.id}/messages", json={"content": PROMPT}, headers=headers)
    assert resp.status_code == 200, resp.text
    return session


async def _start_chat_turn(client, db, headers, world) -> ChatSession:
    session = await _active_session(db)
    world["script"] = [TOOL_RESPONSE]
    resp = await client.post(
        "/chat/api/send",
        json={"prompt": PROMPT, "session_id": session.id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    await _await_turn(session.id)
    return session


async def _await_turn(session_id: str) -> None:
    """Wait for the chat-turn task and its completion follow-ups of this session."""
    task = CHAT_RUN_TASKS.get(session_id)
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=30)
    await asyncio.wait_for(drain_chat_turn_background_tasks(session_id), timeout=30)


async def _approve(client, approval_id: str, headers) -> Any:
    return await client.post(f"/chat/api/approvals/{approval_id}/approve", headers=headers)


@pytest.mark.asyncio
@pytest.mark.committed_db
@pytest.mark.parametrize("start_turn", [_start_api_turn, _start_chat_turn], ids=["api-v1", "chat-api"])
async def test_an_approved_turn_resumes_once_on_either_path(client, db, auth_headers, world, start_turn) -> None:
    session = await start_turn(client, db, auth_headers, world)
    await db.refresh(session)
    assert session.status == "pending_approval"
    assert world["executions"] == 0
    approval = await _pending_approval(db, session.id)
    assert approval.id in (session.metadata_ or {}).get(PAUSED_TURNS_METADATA_KEY, {})

    world["script"] = [TOOL_RESPONSE, FINAL_RESPONSE]
    resp = await _approve(client, approval.id, auth_headers)
    assert resp.status_code == 200, resp.text
    await _await_turn(session.id)

    assert world["script"] == []
    assert world["executions"] == 1
    await db.refresh(session)
    metadata = session.metadata_ or {}
    assert session.status == "active"
    assert metadata.get("run_status") == "completed"
    assert metadata.get("approval_grants") == []
    assert approval.id not in metadata.get(PAUSED_TURNS_METADATA_KEY, {})
    # The resumed turn is its own Chat-turn Product Run (resume ancestry is follow-up work).
    runs = (await db.execute(select(ProductRun).where(ProductRun.session_id == session.id))).scalars().all()
    assert [run.origin for run in runs] == ["chat_turn", "chat_turn"]

    # A replayed approval is refused and runs nothing.
    replay = await _approve(client, approval.id, auth_headers)
    assert replay.status_code == 409 and replay.json()["detail"]["code"] == "approval_already_resolved"
    assert world["executions"] == 1


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_user_without_session_access_cannot_approve(client, db, auth_headers, world) -> None:
    session = await _start_api_turn(client, db, auth_headers, world)
    approval = await _pending_approval(db, session.id)
    stranger = User(
        id=str(uuid.uuid4()),
        username=f"stranger-{uuid.uuid4().hex[:8]}",
        email=f"stranger-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("local-Test-Pass-123"),
        display_name="Stranger",
    )
    db.add(stranger)
    await db.commit()
    stranger_headers = {"Authorization": f"Bearer {create_access_token(stranger.id)}"}

    for action in ("approve", "reject"):
        resp = await client.post(f"/chat/api/approvals/{approval.id}/{action}", headers=stranger_headers)
        assert resp.status_code == 404, resp.text

    await db.refresh(approval)
    assert approval.status == "pending"
    assert world["executions"] == 0
