"""Both session entry paths leave the same persisted end-of-turn facts (roadmap item 5).

A turn sent over ``/api/v1/sessions/{id}/messages`` (in the request) and one over
``/chat/api/send`` (background task) finish through the same completion step
(``turn_settlement``) or failure settlement (``turn_failure``). For a completed, a
paused and a failed turn, both paths must persist the same facts: turn marker
cleared, session status and run state, the Product Run attempt's state, and the
approval binding of a paused turn. Only the HTTP contracts differ, and stay as they
were (``/api/v1`` answers with the messages or propagates the failure).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
import app.agent.providers as providers_module
from app.models import Approval, Message, Project, TurnTrace, User
from app.models import Session as ChatSession
from app.models.runtime.product_run import ProductRun, ProductRunAttempt
from app.services.chat_turn_background import drain_chat_turn_background_tasks
from app.services.session.turn_approval_state import PAUSED_TURNS_METADATA_KEY
from app.services.session.turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY
from app.services.session.turn_tasks import CHAT_RUN_TASKS
from app.tools.definitions import get_all_definitions
from app.tools.registry import TOOL_REGISTRY

TOOL = "get_current_time"
PROMPT = "What time is it?"
TOOL_CALL = {"id": "call_1", "type": "function", "function": {"name": TOOL, "arguments": "{}"}}
PAUSING = {"content": "", "tool_calls": [TOOL_CALL], "usage": {"prompt_tokens": 11, "completion_tokens": 3}}
ANSWER = {"content": "It is midnight UTC.", "tool_calls": None, "usage": {"prompt_tokens": 7, "completion_tokens": 2}}
APPROVAL_POLICY = {"approval_policy": {"require_for_tools": [TOOL]}}

EXPECTED = {
    "completed": {"status": "active", "run": ("completed", "completed"), "attempt": "finished_unverified"},
    "paused": {"status": "pending_approval", "run": ("awaiting_approval", "approval_required"), "attempt": "waiting_approval"},
    "failed": {"status": "active", "run": ("failed", "error"), "attempt": "failed"},
}


class PreparationFailedError(RuntimeError):
    pass


@pytest.fixture
def world(monkeypatch):
    """A scripted provider (no network); ``fail`` makes the run raise before any model call."""
    state: dict[str, Any] = {"script": [], "fail": False}

    async def fixed_time(params, context):
        return {"utc_time_iso": "2026-09-30T00:00:00+00:00", "timezone_name": "UTC"}

    monkeypatch.setattr(TOOL_REGISTRY[TOOL], "execute", fixed_time)
    original_prepare = engine_module._prepare_agent_run

    async def prepare(**kwargs):
        if state["fail"]:
            raise PreparationFailedError("fixed test failure")
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


async def _session(db) -> ChatSession:
    project = Project(name=f"turn-end-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = ChatSession(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat", status="active", metadata_={}
    )
    db.add(session)
    await db.commit()
    return session


async def _send_api(client, session_id: str, headers) -> None:
    resp = await client.post(f"/api/v1/sessions/{session_id}/messages", json={"content": PROMPT}, headers=headers)
    assert resp.status_code == 200, resp.text


async def _send_chat(client, session_id: str, headers) -> None:
    resp = await client.post(
        "/chat/api/send", json={"prompt": PROMPT, "session_id": session_id}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    task = CHAT_RUN_TASKS.get(session_id)
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=30)


async def _end_of_turn_facts(db, session_id: str) -> dict[str, Any]:
    db.expire_all()
    session = await db.get(ChatSession, session_id)
    metadata = dict(session.metadata_ or {})
    user_message = (
        await db.execute(select(Message).where(Message.session_id == session_id, Message.role == "user"))
    ).scalar_one()
    run = (await db.execute(select(ProductRun).where(ProductRun.session_id == session_id))).scalar_one()
    attempt = (await db.execute(select(ProductRunAttempt).where(ProductRunAttempt.run_id == run.id))).scalar_one()
    approval = (await db.execute(select(Approval).where(Approval.session_id == session_id))).scalar_one_or_none()
    binding = (metadata.get(PAUSED_TURNS_METADATA_KEY) or {}).get(approval.id) if approval else None
    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id))).scalars().all()
    snapshots = [(trace.context_snapshot_json or {}).get(TURN_EXECUTION_SNAPSHOT_KEY) or {} for trace in traces]
    return {
        "marker": [key for key in ("current_turn_user_message_id", "current_turn_started_at") if key in metadata],
        "resume_state": metadata.get("resume_state"),
        "status": session.status,
        "run": (metadata.get("run_status"), metadata.get("run_completion_reason")),
        "attempt": attempt.state,
        "run_turn_message_is_the_turn": run.turn_user_message_id == user_message.id,
        "binding_is_the_turn": None if binding is None else binding.get("user_message_id") == user_message.id,
        # Preparation always builds the execution profile, so every trace's snapshot carries it.
        "profile_in_snapshots": sorted({bool((s.get("execution_profile") or {}).get("present")) for s in snapshots}),
        "profile_on_session": bool((metadata.get("execution_profile") or {}).get("profile_id")),
    }


@pytest.mark.asyncio
@pytest.mark.committed_db
@pytest.mark.parametrize("outcome", ["completed", "paused", "failed"])
async def test_both_paths_leave_the_same_end_of_turn_facts(client, db, auth_headers, world, outcome) -> None:
    facts: dict[str, dict[str, Any]] = {}
    for path in ("api-v1", "chat-api"):
        session = await _session(db)
        world["script"] = [ANSWER] if outcome == "completed" else [PAUSING]
        world["fail"] = outcome == "failed"
        if path == "chat-api":
            await _send_chat(client, session.id, auth_headers)
        elif outcome == "failed":
            # /api/v1 keeps its HTTP contract: the failure propagates (a 500 in production) after settling.
            with pytest.raises(PreparationFailedError):
                await _send_api(client, session.id, auth_headers)
        else:
            await _send_api(client, session.id, auth_headers)
        await asyncio.wait_for(drain_chat_turn_background_tasks(session.id), timeout=30)
        facts[path] = await _end_of_turn_facts(db, session.id)

    assert facts["api-v1"] == facts["chat-api"]
    expected = EXPECTED[outcome]
    assert facts["api-v1"]["marker"] == []
    assert facts["api-v1"]["resume_state"] is None
    assert facts["api-v1"]["status"] == expected["status"]
    assert facts["api-v1"]["run"] == expected["run"]
    assert facts["api-v1"]["attempt"] == expected["attempt"]
    assert facts["api-v1"]["run_turn_message_is_the_turn"] is True
    assert facts["api-v1"]["binding_is_the_turn"] is (True if outcome == "paused" else None)
    assert facts["api-v1"]["profile_in_snapshots"] == ([] if outcome == "failed" else [True])
    assert facts["api-v1"]["profile_on_session"] is True
